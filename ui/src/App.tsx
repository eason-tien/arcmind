import { useState } from "react";
import { motion } from "framer-motion";
import { AgentCharacterSelector, AgentCharacterDisplay } from "../components/AgentCharacter";
import { AgentCharacter, youngAgentCharacters } from "../types/agentCharacter";
import { CaseManagement } from "../components/CaseManagement";

type Page = 'home' | 'cases';

function App() {
  const [selectedCharacter, setSelectedCharacter] = useState<AgentCharacter | null>(null);
  const [currentPage, setCurrentPage] = useState<Page>('cases');

  // If not on home page, show Case Management
  if (currentPage === 'cases') {
    return (
      <div className="h-screen">
        <CaseManagement />
      </div>
    );
  }

  // Home page with Agent Characters
  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 to-gray-100 py-12 px-4">
      {/* Navigation */}
      <div className="max-w-6xl mx-auto mb-8">
        <nav className="flex justify-end gap-4">
          <button
            onClick={() => setCurrentPage('cases')}
            className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
          >
            📋 案例管理
          </button>
          <button
            onClick={() => setCurrentPage('home')}
            className="px-4 py-2 border rounded-lg hover:bg-gray-50"
          >
            🏠 首頁
          </button>
        </nav>
      </div>

      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-4xl font-bold text-gray-800 mb-4">
            🤖 AI Agent Characters
          </h1>
          <p className="text-gray-600 max-w-2xl mx-auto">
            Meet our friendly AI agents! All characters are designed to be 
            <span className="font-bold text-blue-600"> under 3 years old</span> — 
            young, curious, and always ready to help.
          </p>
        </div>

        {/* Character Cards */}
        <div className="mb-12">
          <h2 className="text-2xl font-semibold text-gray-700 mb-6 text-center">
            Choose Your Agent
          </h2>
          <AgentCharacterSelector 
            onSelect={setSelectedCharacter}
            selectedId={selectedCharacter?.id}
          />
        </div>

        {/* Selected Character Display */}
        {selectedCharacter && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-white rounded-3xl shadow-xl p-8 text-center"
          >
            <h3 className="text-2xl font-bold text-gray-800 mb-6">
              🎯 Selected Character
            </h3>
            <div className="flex justify-center mb-6">
              <AgentCharacterDisplay 
                character={selectedCharacter} 
                size="lg" 
              />
            </div>
            
            <div className="max-w-md mx-auto space-y-3">
              <p className="text-gray-600">
                <strong>Personality:</strong> {selectedCharacter.personality}
              </p>
              <p className="text-gray-600">
                <strong>Skills:</strong> {selectedCharacter.skills.join(", ")}
              </p>
              <p className="text-gray-600">
                <strong>About:</strong> {selectedCharacter.description}
              </p>
            </div>
          </motion.div>
        )}

        {/* All Characters Grid */}
        <div className="mt-16">
          <h2 className="text-2xl font-semibold text-gray-700 mb-6 text-center">
            All Available Agents
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {youngAgentCharacters.map((char) => (
              <div key={char.id} className="text-center">
                <AgentCharacterDisplay character={char} size="md" />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
