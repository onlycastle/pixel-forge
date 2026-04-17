import { useState } from "react";
import { PersonForge } from "./components/PersonForge";
import { PlaceableForge } from "./components/PlaceableForge";
import "./App.css";

type Tab = "character" | "placeables";

export default function App() {
  const [tab, setTab] = useState<Tab>("character");

  return (
    <div className="app">
      <header className="app__header">
        <h1>Pixel Forge</h1>
        <nav className="app__tabs">
          <button
            className={`app__tab ${tab === "character" ? "app__tab--active" : ""}`}
            onClick={() => setTab("character")}
          >
            Character
          </button>
          <button
            className={`app__tab ${tab === "placeables" ? "app__tab--active" : ""}`}
            onClick={() => setTab("placeables")}
          >
            Placeables
          </button>
        </nav>
      </header>
      <main className="app__main">
        {tab === "character" ? <PersonForge /> : <PlaceableForge />}
      </main>
    </div>
  );
}
