import { useEffect, useState } from "react";
import ProjectList from "./ProjectList";
import ProjectDetail from "./ProjectDetail";
function currentProject() { const match = /^#\/projects\/([A-Za-z0-9-]+)(?:\?.*)?$/.exec(window.location.hash); return match?.[1] ?? null; }
export default function Workbench({csrf}: {csrf: string}) {
  const [id, setId] = useState(currentProject);
  useEffect(() => { const changed = () => setId(currentProject()); window.addEventListener("hashchange", changed); return () => window.removeEventListener("hashchange", changed); }, []);
  return id ? <ProjectDetail key={id} id={id} csrf={csrf} /> : <ProjectList csrf={csrf} />;
}
