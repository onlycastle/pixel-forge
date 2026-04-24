import { useCallback, useEffect, useState } from "react";
import { PersonForge } from "./components/PersonForge";
import { PlaceableForge } from "./components/PlaceableForge";
import "./App.css";

type Tab = "character" | "placeables";

function readTab(): Tab {
  const h = location.hash.replace("#", "");
  return h === "placeables" ? "placeables" : "character";
}

export default function App() {
  const [tab, setTab] = useState<Tab>(readTab);

  const switchTab = useCallback((t: Tab) => {
    setTab(t);
    location.hash = t;
  }, []);

  useEffect(() => {
    const onHash = () => setTab(readTab());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return (
    <div className="app">
      <header className="app__header">
        <h1>Pixel Forge</h1>
        <nav className="app__tabs">
          <button
            className={`app__tab ${tab === "character" ? "app__tab--active" : ""}`}
            onClick={() => switchTab("character")}
          >
            Character
          </button>
          <button
            className={`app__tab ${tab === "placeables" ? "app__tab--active" : ""}`}
            onClick={() => switchTab("placeables")}
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
