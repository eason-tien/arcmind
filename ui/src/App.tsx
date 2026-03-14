import { Sidebar } from "./components/Sidebar/Sidebar";
import { ChatArea } from "./components/Chat/ChatArea";

function App() {
  return (
    <div className="h-screen w-screen flex bg-background text-foreground overflow-hidden">
      <Sidebar />
      <ChatArea />
    </div>
  );
}

export default App;
