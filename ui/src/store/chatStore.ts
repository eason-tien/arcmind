import { create } from 'zustand';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8100';

export interface Message {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: number;
}

export interface Session {
    id: string;
    title: string;
    updatedAt: number;
}

export type AppTab = 'chat' | 'dashboard' | 'memory';

interface ChatState {
    isSidebarOpen: boolean;
    toggleSidebar: () => void;

    activeTab: AppTab;
    setActiveTab: (tab: AppTab) => void;

    sessions: Session[];
    activeSessionId: string | null;
    setActiveSession: (id: string) => void;

    messages: Message[];
    addMessage: (msg: Message) => void;
    setMessages: (msgs: Message[]) => void;

    isGenerating: boolean;
    setGenerating: (val: boolean) => void;

    isVoiceMode: boolean;
    toggleVoiceMode: () => void;
    voiceState: 'idle' | 'listening' | 'thinking' | 'speaking';
    setVoiceState: (state: 'idle' | 'listening' | 'thinking' | 'speaking') => void;

    // Audio device settings
    availableAudioDevices: MediaDeviceInfo[];
    selectedAudioDeviceId: string | null;
    audioError: string | null;
    setSelectedAudioDevice: (id: string) => void;
    fetchAudioDevices: () => Promise<void>;

    vadSensitivity: number;
    setVadSensitivity: (val: number) => void;

    submitVoiceAudio?: (blob: Blob) => void;
    sendMessage: (text: string) => Promise<void>;
    deleteSession: (sessionId: string) => Promise<void>;

    fetchSessions: () => Promise<void>;
    fetchMessages: (sessionId: string) => Promise<void>;
}

export const useChatStore = create<ChatState>((set) => ({
    isSidebarOpen: true,
    toggleSidebar: () => set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),

    activeTab: 'chat',
    setActiveTab: (tab) => set({ activeTab: tab }),

    sessions: [
        { id: '1', title: 'New Conversation', updatedAt: Date.now() }
    ],
    activeSessionId: '1',
    setActiveSession: (id) => set({ activeSessionId: id, activeTab: 'chat' }),

    messages: [],
    addMessage: (msg) => set((state) => ({ messages: [...state.messages, msg] })),
    setMessages: (msgs) => set({ messages: msgs }),

    isGenerating: false,
    setGenerating: (val) => set({ isGenerating: val }),

    isVoiceMode: false,
    toggleVoiceMode: () => set((state) => ({ isVoiceMode: !state.isVoiceMode, voiceState: 'idle' })),
    voiceState: 'idle',
    setVoiceState: (state) => set({ voiceState: state }),

    availableAudioDevices: [],
    selectedAudioDeviceId: null,
    audioError: null,

    vadSensitivity: 10,
    setVadSensitivity: (val) => set({ vadSensitivity: val }),

    setSelectedAudioDevice: (id) => set({ selectedAudioDeviceId: id }),
    fetchAudioDevices: async () => {
        if (!navigator.mediaDevices) {
            set({ audioError: "Browser blocked audio access. (HTTPS or localhost required)" });
            return;
        }
        try {
            await navigator.mediaDevices.getUserMedia({ audio: true }); // Trigger permission check first
            const devices = await navigator.mediaDevices.enumerateDevices();
            const audioInputs = devices.filter(device => device.kind === 'audioinput');
            set({
                availableAudioDevices: audioInputs,
                selectedAudioDeviceId: audioInputs.length > 0 ? audioInputs[0].deviceId : null,
                audioError: null
            });
        } catch (err: any) {
            console.error("Failed to fetch audio devices:", err);
            set({ audioError: err.message || "Microphone permission denied" });
        }
    },

    sendMessage: async (text: string) => {
        const state = useChatStore.getState();
        const activeSessionId = state.activeSessionId;



        const reqBody = {
            session_id: activeSessionId,
            text: text
        };

        try {
            set({ isGenerating: true });
            const res = await fetch(`${API_BASE}/v1/chat/message`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(reqBody)
            });

            if (!res.ok) {
                console.error("Message send failed:", await res.text());
                return;
            }

            const data = await res.json();

            const newMessages: Message[] = [
                { id: `user_${Date.now()}`, role: 'user', content: text, timestamp: Date.now() },
                { id: `assistant_${Date.now() + 1}`, role: 'assistant', content: data.text, timestamp: Date.now() + 1 }
            ];

            set((state) => ({
                messages: [...state.messages, ...newMessages]
            }));

        } catch (err) {
            console.error("Error sending message:", err);
        } finally {
            set({ isGenerating: false });
        }
    },

    submitVoiceAudio: async (blob: Blob) => {
        const state = useChatStore.getState();
        const activeSessionId = state.activeSessionId;
        try {
            set({ isGenerating: true, voiceState: 'thinking' });

            const formData = new FormData();
            formData.append('audio', blob, 'voice.webm');

            // Hardcode to localhost API since Electron running from file:// cannot use relative proxies


            // Send to our new backend endpoint
            const res = await fetch(`${API_BASE}/v1/chat/audio?session_id=${activeSessionId}`, {
                method: 'POST',
                body: formData
            });

            if (!res.ok) {
                console.error("Audio upload failed:", await res.text());
                return;
            }

            const data = await res.json();

            // Push the transcript (user message) and the response (assistant message)
            const newMessages: Message[] = [
                { id: `user_${Date.now()}`, role: 'user', content: data.transcript, timestamp: Date.now() },
                { id: `assistant_${Date.now()}`, role: 'assistant', content: data.text, timestamp: Date.now() + 1 }
            ];

            set((state) => ({
                messages: [...state.messages, ...newMessages]
            }));

            // If backend provided TTS audio, play it now
            if (data.audio_base64) {
                set({ voiceState: 'speaking' });
                try {
                    const audioSrc = `data:audio/ogg;base64,${data.audio_base64}`;
                    const audio = new Audio(audioSrc);
                    audio.onended = () => {
                        set({ voiceState: 'idle' });
                    };
                    await audio.play();
                } catch (e) {
                    console.error("Failed to play TTS audio:", e);
                    set({ voiceState: 'idle' });
                }
            } else {
                set({ voiceState: 'idle' });
            }

        } catch (err) {
            console.error("Error submitting voice audio:", err);
            set({ voiceState: 'idle' });
        } finally {
            set({ isGenerating: false });
        }
    },

    fetchSessions: async () => {
        try {
            const res = await fetch(`${API_BASE}/v1/chat/sessions`);
            const data = await res.json();
            if (data.sessions) {
                const loadedSessions = data.sessions.map((s: any) => ({
                    id: s.session_id,
                    title: s.session_id,
                    updatedAt: new Date(s.last_activity).getTime()
                }));
                // If there are sessions, replace the dummy one
                if (loadedSessions.length > 0) {
                    set({ sessions: loadedSessions });
                }
            }
        } catch (err) {
            console.error('Failed to fetch sessions:', err);
        }
    },

    deleteSession: async (sessionId: string) => {
        try {
            const res = await fetch(`${API_BASE}/v1/chat/sessions/${sessionId}`, {
                method: 'DELETE'
            });
            if (res.ok) {
                set((state) => ({
                    sessions: state.sessions.filter(s => s.id !== sessionId),
                    activeSessionId: state.activeSessionId === sessionId ? null : state.activeSessionId
                }));
            } else {
                console.error("Failed to delete session:", await res.text());
            }
        } catch (err) {
            console.error('Failed to delete session:', err);
        }
    },

    fetchMessages: async (sessionId: string) => {
        try {

            const res = await fetch(`${API_BASE}/v1/chat/sessions/${sessionId}/history`); // Changed to absolute URL
            const data = await res.json();
            if (data.messages) {
                // Parse timestamp string back to number for ChatState
                const loadedMsgs = data.messages.map((m: any) => ({
                    id: m.id,
                    role: m.role,
                    content: m.content,
                    timestamp: m.timestamp ? new Date(m.timestamp).getTime() : Date.now()
                }));
                set({ messages: loadedMsgs });
            }
        } catch (err) {
            console.error('Failed to fetch messages for session:', err);
        }
    }
}));
