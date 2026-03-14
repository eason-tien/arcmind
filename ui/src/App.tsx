import { Sidebar } from "./components/Sidebar/Sidebar";
import { ChatArea } from "./components/Chat/ChatArea";
import { ThemeProvider } from "./lib/ThemeProvider";
import { NotificationProvider } from "./components/NotificationCenter";

function App() {
  return (
    <ThemeProvider>
      <NotificationProvider>
        <div className="h-screen w-screen flex bg-background text-foreground overflow-hidden">
          <Sidebar />
          <ChatArea />
        </div>
      </NotificationProvider>
    </ThemeProvider>
  );
}

export default App;
