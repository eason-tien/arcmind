import { VoiceOverlay } from './components/Chat/VoiceOverlay';
import { useChatStore } from './store/chatStore';
import { Sidebar } from './components/Sidebar/Sidebar';
import { ChatArea } from './components/Chat/ChatArea';

function App() {
  const isVoiceMode = useChatStore(state => state.isVoiceMode);

  if (isVoiceMode) {
    return (
      <div className="flex h-screen w-full bg-black overflow-hidden selection:bg-primary/30 titlebar-drag-region text-white place-content-center items-center justify-center">
        {/* Debug: Print DOM state after 3s to console */}
        {(() => {
          setTimeout(() => {
            console.log("[Renderer/Debug] Root HTML size:", document.getElementById("root")?.innerHTML.length);
            console.log("[Renderer/Debug] isVoiceMode:", useChatStore.getState().isVoiceMode);
          }, 3000);
          return null;
        })()}

        <main className="flex-1 flex flex-col min-w-0 h-full relative z-10 no-drag items-center justify-center">
          <VoiceOverlay />
        </main>
      </div>
    );
  }

  return (
    <div className="flex h-screen w-full bg-background overflow-hidden selection:bg-primary/30 text-foreground">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0 h-full relative z-10 transition-all duration-300">
        <ChatArea />
      </main>
    </div>
  );
}

export default App;
