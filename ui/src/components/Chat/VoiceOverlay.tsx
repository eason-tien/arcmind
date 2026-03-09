import { motion } from 'framer-motion';
import { useChatStore } from '../../store/chatStore';
import { X, Settings } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useEffect, useRef, useState } from 'react';

export function VoiceOverlay() {
    const {
        isVoiceMode, toggleVoiceMode, voiceState, setVoiceState, submitVoiceAudio,
        availableAudioDevices, selectedAudioDeviceId, setSelectedAudioDevice, fetchAudioDevices, audioError,
        vadSensitivity, setVadSensitivity
    } = useChatStore();

    // Web Audio API & MediaRecorder references
    const audioContextRef = useRef<AudioContext | null>(null);
    const analyzerRef = useRef<AnalyserNode | null>(null);
    const mediaRecorderRef = useRef<MediaRecorder | null>(null);
    const streamRef = useRef<MediaStream | null>(null);
    const animationFrameRef = useRef<number>(0);
    const audioChunksRef = useRef<BlobPart[]>([]);

    // Real-time audio level (0-100)
    const [audioLevel, setAudioLevel] = useState(0);

    const [isStreamReady, setIsStreamReady] = useState(false);

    // Voice Activity Detection Refs
    const voiceStateRef = useRef(voiceState);
    const isSpeakingRef = useRef(false);
    const hasSpokenThisSessionRef = useRef(false);
    const silenceStartRef = useRef<number | null>(null);
    const speakingStartRef = useRef<number | null>(null); // Track duration of the sound spike
    const vadSensitivityRef = useRef(vadSensitivity);

    // Keep voice state ref updated for animationFrame closure
    useEffect(() => {
        voiceStateRef.current = voiceState;
    }, [voiceState]);

    useEffect(() => {
        vadSensitivityRef.current = vadSensitivity;
    }, [vadSensitivity]);

    // Effect 1: Core Stream and Audio Context Maintenance
    useEffect(() => {
        if (!isVoiceMode) return;

        let isMounted = true;

        const initStream = async () => {
            try {
                if (!navigator.mediaDevices) {
                    throw new Error("HTTP Insecure context blocks MediaDevices API.");
                }

                console.log("[VoiceOverlay] Requesting microphone permission...", selectedAudioDeviceId);
                const stream = await navigator.mediaDevices.getUserMedia({
                    audio: selectedAudioDeviceId ? { deviceId: { exact: selectedAudioDeviceId } } : true
                });
                console.log("[VoiceOverlay] Microphone permission granted.");

                if (!isMounted) {
                    stream.getTracks().forEach(track => track.stop());
                    return;
                }
                streamRef.current = stream;

                const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
                const audioContext = new AudioContextClass();
                audioContextRef.current = audioContext;

                const analyzer = audioContext.createAnalyser();
                analyzer.fftSize = 256;
                analyzerRef.current = analyzer;

                const source = audioContext.createMediaStreamSource(stream);
                source.connect(analyzer);

                const dataArray = new Uint8Array(analyzer.frequencyBinCount);

                const updateLevel = () => {
                    analyzer.getByteFrequencyData(dataArray);
                    let sum = 0;
                    for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
                    const average = sum / dataArray.length;

                    if (isMounted) {
                        setAudioLevel(average);

                        // Voice Activity Detection (VAD)
                        if (voiceStateRef.current === 'listening') {
                            const vadGate = vadSensitivityRef.current * 10;
                            if (average > vadGate) { // Dynamic Speaking volume threshold
                                if (!isSpeakingRef.current) {
                                    isSpeakingRef.current = true;
                                    speakingStartRef.current = Date.now();
                                }
                                hasSpokenThisSessionRef.current = true;
                                silenceStartRef.current = null;
                            } else {
                                if (isSpeakingRef.current) {
                                    if (silenceStartRef.current === null) {
                                        silenceStartRef.current = Date.now();
                                    } else if (Date.now() - silenceStartRef.current > 1000) {
                                        // 1.0s of silence detected -> evaluate if the noise was a real sentence or just a quick spike
                                        const speakingDuration = Date.now() - (speakingStartRef.current || 0);

                                        if (speakingDuration < 500) {
                                            // Transient spike (cough, desk tap, keyboard click) - Reject it quietly
                                            console.log("[VoiceOverlay] Rejected short audio spike:", speakingDuration, "ms");

                                            // Wipe the current recording data and silently restart the MediaRecorder without triggering AI API
                                            audioChunksRef.current = [];
                                            hasSpokenThisSessionRef.current = false;

                                            if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
                                                // Pausing & Resuming is cleaner than destroying the entire object
                                                mediaRecorderRef.current.pause();
                                                setTimeout(() => {
                                                    if (mediaRecorderRef.current?.state === 'paused') {
                                                        mediaRecorderRef.current.resume();
                                                    }
                                                }, 50);
                                            }
                                        } else {
                                            // Legitimate speech detected -> Trigger audio submission
                                            if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
                                                mediaRecorderRef.current.stop();
                                            }
                                        }

                                        // Reset state machine hooks
                                        isSpeakingRef.current = false;
                                        silenceStartRef.current = null;
                                        speakingStartRef.current = null;
                                    }
                                }
                            }
                        }

                        animationFrameRef.current = requestAnimationFrame(updateLevel);
                    }
                };
                updateLevel();
                setIsStreamReady(true);

            } catch (err) {
                console.error("[VoiceOverlay] Failed to access microphone.", err);
                if (isMounted) setVoiceState('listening');
            }
        };

        const initTimeout = setTimeout(() => {
            initStream();
        }, 300);

        return () => {
            isMounted = false;
            setIsStreamReady(false);
            clearTimeout(initTimeout);

            if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
            if (audioContextRef.current?.state !== 'closed') audioContextRef.current?.close();
            if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
                mediaRecorderRef.current.stop();
            }
            if (streamRef.current) streamRef.current.getTracks().forEach(track => track.stop());
        };
    }, [isVoiceMode, selectedAudioDeviceId, setVoiceState]);

    // Effect 2: Manage MediaRecorder sessions based on voice state
    useEffect(() => {
        if (!isVoiceMode || !isStreamReady || !streamRef.current) return;

        // Auto-start a new recording if we returned to idle (Agent finished speaking)
        if (voiceState === 'idle') {
            const mediaRecorder = new MediaRecorder(streamRef.current, { mimeType: 'audio/webm' });
            mediaRecorderRef.current = mediaRecorder;
            audioChunksRef.current = [];

            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) audioChunksRef.current.push(event.data);
            };

            mediaRecorder.onstop = () => {
                // Ensure we only submit if they generated noise (prevents empty audio on modal close)
                if (audioChunksRef.current.length > 0 && hasSpokenThisSessionRef.current) {
                    const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
                    submitVoiceAudio?.(audioBlob);
                }
            };

            mediaRecorder.start();
            setVoiceState('listening');
            isSpeakingRef.current = false;
            hasSpokenThisSessionRef.current = false;
            silenceStartRef.current = null;
        }
    }, [isVoiceMode, isStreamReady, voiceState, setVoiceState, submitVoiceAudio]);

    useEffect(() => {
        if (isVoiceMode) {
            fetchAudioDevices();
        }
    }, [isVoiceMode, fetchAudioDevices]);

    const getStatusText = () => {
        if (audioError) return '麥克風發生錯誤';
        switch (voiceState) {
            case 'listening':
                return 'Arci 聆聽中...';
            case 'thinking':
                return '思考中...';
            case 'speaking':
                return 'Arci 回覆中...';
            default:
                return '語音模式已待命';
        }
    };

    return (
        <>
            {isVoiceMode && (
                <div
                    className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md"
                >
                    {/* Close Button */}
                    <button
                        onClick={toggleVoiceMode}
                        className="absolute top-8 right-8 p-3 bg-white/10 hover:bg-white/20 rounded-full transition-colors text-white"
                    >
                        <X size={24} />
                    </button>

                    <div className="flex flex-col items-center justify-center w-full max-w-lg">

                        {/* Status Text (Top) */}
                        <motion.div
                            key={voiceState}
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            className="text-white/60 text-sm tracking-widest font-mono uppercase mb-16"
                        >
                            {getStatusText()}
                        </motion.div>

                        {/* AI Core Sphere Container */}
                        <motion.div
                            className="relative w-64 h-64 md:w-80 md:h-80 flex items-center justify-center"
                            animate={{
                                scale: voiceState === 'speaking' ? [1, 1.05, 1] : 1,
                            }}
                            transition={{
                                repeat: voiceState === 'speaking' ? Infinity : 0,
                                duration: 0.8,
                                ease: "easeInOut"
                            }}
                        >
                            {/* Inner Glow / Shadow depending on state */}
                            <div className={cn(
                                "absolute inset-0 rounded-full blur-[60px] transition-all duration-1000",
                                voiceState === 'speaking' ? "bg-cyan-400/50" :
                                    voiceState === 'thinking' ? "bg-purple-500/40" :
                                        "bg-blue-400/30"
                            )} />

                            {/* PURE CSS SPHERE CORE */}
                            <div className="relative w-full h-full rounded-full flex items-center justify-center overflow-hidden">
                                {/* Base core */}
                                <div className={cn(
                                    "absolute inset-4 rounded-full transition-all duration-700 blur-[2px]",
                                    voiceState === 'thinking' ? "bg-gradient-to-tr from-purple-600/80 to-blue-400/80"
                                        : "bg-gradient-to-tr from-cyan-500/80 to-blue-500/80"
                                )} />

                                {/* Inner bright star */}
                                <div className={cn(
                                    "absolute inset-12 rounded-full blur-md transition-all duration-500",
                                    voiceState === 'thinking' ? "bg-white/60" : "bg-cyan-200/80"
                                )} />

                                {/* Organic rotating plasma layers */}
                                <motion.div
                                    className={cn(
                                        "absolute inset-0 rounded-full border-[8px] mix-blend-overlay filter blur-[4px]",
                                        voiceState === 'thinking' ? "border-purple-300" : "border-cyan-200"
                                    )}
                                    animate={{ rotate: 360, scale: [1, 1.05, 1] }}
                                    transition={{ repeat: Infinity, duration: voiceState === 'thinking' ? 3 : 8, ease: "linear" }}
                                />
                                <motion.div
                                    className={cn(
                                        "absolute inset-4 rounded-full border-[4px] mix-blend-overlay filter blur-[2px]",
                                        voiceState === 'thinking' ? "border-pink-300" : "border-blue-200"
                                    )}
                                    animate={{ rotate: -360, scale: [1, 1.1, 1] }}
                                    transition={{ repeat: Infinity, duration: 5, ease: "linear" }}
                                />

                                {/* Dynamic audio reactive overlay scale */}
                                <motion.div
                                    className="absolute inset-8 rounded-full bg-white/20 blur-xl"
                                    animate={{
                                        scale: 1 + (Math.max(0, audioLevel - (vadSensitivity * 10)) / 100) * 0.5
                                    }}
                                    transition={{ type: "spring", bounce: 0, duration: 0.1 }}
                                />
                            </div>
                        </motion.div>

                        {/* Audio Wave (Real-time dynamic visualization) */}
                        <div className="h-24 flex items-end justify-center gap-1 mt-16 overflow-hidden">
                            {Array.from({ length: 30 }).map((_, i) => {
                                // Calculate a deterministic but varied height modifier based on the audioLevel
                                // Center bars jump higher than outer bars
                                const distanceFromCenter = Math.abs(15 - i);
                                const heightMax = 100 - (distanceFromCenter * 4);

                                // Noise floor clamp: only animate if above VAD sensitivity
                                const vadGate = vadSensitivity * 10;
                                const effectiveAudio = Math.max(0, audioLevel - vadGate);
                                const isIdle = effectiveAudio === 0;

                                // Randomizer tied loosely to index to make it look organic
                                const randomOffset = (i % 5) * 2;

                                // Computed dynamic height, scaled up a bit since effectiveAudio is smaller
                                const targetHeight = isIdle
                                    ? 4  // Min idle height
                                    : Math.max(4, (effectiveAudio / 50) * heightMax + randomOffset + (Math.random() * (effectiveAudio / 5)));

                                return (
                                    <motion.div
                                        key={i}
                                        className="w-1.5 bg-white/70 rounded-full"
                                        animate={{
                                            // Fallback to fake simulation if state is explicitly 'speaking' (like AI TTS responding)
                                            height: voiceState === 'speaking'
                                                ? [Math.random() * 20 + 10, Math.random() * 60 + 20, Math.random() * 20 + 10]
                                                : targetHeight
                                        }}
                                        transition={{
                                            type: "spring",
                                            stiffness: 300,
                                            damping: 20,
                                            // Only loop the transition if we are in proxy 'speaking' mode
                                            repeat: voiceState === 'speaking' ? Infinity : 0,
                                            duration: voiceState === 'speaking' ? 0.3 + Math.random() * 0.2 : undefined,
                                            ease: voiceState === 'speaking' ? "easeInOut" : undefined
                                        }}
                                    />
                                );
                            })}
                        </div>

                    </div>

                    {/* Controls & Device Selection (Bottom) */}
                    <div className="absolute bottom-12 flex flex-col items-center gap-6">

                        <div className="flex items-center gap-6">
                            <div className="flex flex-col items-center justify-center opacity-50">
                                {voiceState === 'listening' ? (
                                    <span className="text-xs tracking-wider">請直接開始說話...</span>
                                ) : (
                                    <span className="text-xs tracking-wider">處理中請稍候...</span>
                                )}
                            </div>
                        </div>

                        {/* Device Selector or Error */}
                        {audioError ? (
                            <div className="text-red-400 text-xs text-center px-4 bg-red-900/20 py-2 rounded-full whitespace-pre-wrap">
                                {audioError.includes("HTTP") || audioError.includes("blocked") ? "安全限制：請改用 localhost 或設定 HTTPS 才能使用麥克風" : audioError}
                            </div>
                        ) : availableAudioDevices.length > 0 && (
                            <div className="flex flex-col md:flex-row items-center gap-4">
                                <div className="flex items-center gap-2 bg-black/40 backdrop-blur-md px-4 py-2 rounded-full border border-white/10">
                                    <Settings size={14} className="text-white/50" />
                                    <select
                                        className="bg-transparent text-white/70 text-xs outline-none cursor-pointer w-48 truncate"
                                        value={selectedAudioDeviceId || ''}
                                        onChange={(e) => {
                                            setSelectedAudioDevice(e.target.value);
                                        }}
                                    >
                                        {availableAudioDevices.map(device => (
                                            <option key={device.deviceId} value={device.deviceId} className="bg-neutral-900">
                                                {device.label || `Microphone ${device.deviceId.substring(0, 5)}...`}
                                            </option>
                                        ))}
                                    </select>
                                </div>

                                <div className="flex items-center gap-3 bg-black/40 backdrop-blur-md px-4 py-2 rounded-full border border-white/10 group cursor-pointer" title="調整環境抗噪（收音門檻值）。背景愈吵，可以調愈高免得被雜音輕易觸發。">
                                    <span className="text-white/50 text-[10px] uppercase font-bold tracking-wider">靈敏度</span>
                                    <input
                                        type="range"
                                        min="1"
                                        max="20"
                                        value={vadSensitivity}
                                        onChange={(e) => setVadSensitivity(parseInt(e.target.value))}
                                        className="w-24 accent-cyan-400"
                                    />
                                    <span className="text-white/70 text-xs font-mono w-4 text-right">{vadSensitivity}</span>
                                </div>
                            </div>
                        )}
                    </div>

                </div>
            )}
        </>
    );
}
