import { PersonForge } from "./components/PersonForge";
import "./App.css";

export default function App() {
  return (
    <div className="app">
      <header className="app__header">
        <h1>Pixel Forge</h1>
        <span className="app__subtitle">Character Generator</span>
      </header>
      <main className="app__main">
        <PersonForge />
      </main>
    </div>
  );
}
