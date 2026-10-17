import { useState } from "react";
import { ErrorPanel } from "./components/ErrorPanel";
import { Header, type Tab } from "./components/Header";
import { ManagementTab } from "./features/management/ManagementTab";
import { SttTab } from "./features/stt/SttTab";
import { TtsTab } from "./features/tts/TtsTab";

export function App() {
  const [tab, setTab] = useState<Tab>(() => (localStorage.getItem("tab") as Tab) || "management");
  const select = (t: Tab) => {
    setTab(t);
    localStorage.setItem("tab", t);
  };
  // Tabs stay mounted so running rows keep their sessions while you look elsewhere.
  return (
    <div className="min-h-screen pb-16">
      <Header tab={tab} onTab={select} />
      <main className="mx-auto max-w-[1600px] p-4">
        <div hidden={tab !== "management"}>
          <ManagementTab />
        </div>
        <div hidden={tab !== "tts"}>
          <TtsTab />
        </div>
        <div hidden={tab !== "stt"}>
          <SttTab />
        </div>
      </main>
      <ErrorPanel />
    </div>
  );
}
