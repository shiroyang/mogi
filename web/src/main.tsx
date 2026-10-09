import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Link, Navigate, Outlet, RouterProvider, useSearchParams } from "react-router";
import { Spinner, Toasts } from "./components/ui";
import { Home } from "./pages/Home";
import "./theme.css";
import "./pages.css";

// The editor chunk (CodeMirror) only loads when a problem is opened.
const Problems = lazy(() => import("./pages/Problems").then(m => ({ default: m.Problems })));
const Problem = lazy(() => import("./pages/Problem").then(m => ({ default: m.Problem })));

function Root() {
  return (
    <>
      <Suspense fallback={<main className="page"><Spinner label="Loading…" /></main>}><Outlet /></Suspense>
      <Toasts />
    </>
  );
}

/** /problem.html?id=Amazon%2FA16 from old bookmarks, the CLI, or the mirror README. */
function LegacyProblem() {
  const [q] = useSearchParams();
  const id = q.get("id") || "";
  if (id.includes("/")) return <Navigate to={`/problem/${id.split("/").map(encodeURIComponent).join("/")}`} replace />;
  return <Navigate to={`/problems${id ? `?open=${encodeURIComponent(id)}` : ""}`} replace />;
}

function NotFound() {
  return (
    <main className="page" style={{ paddingTop: 60, textAlign: "center" }}>
      <h1 style={{ fontSize: 28, margin: "0 0 8px" }}>Nothing here.</h1>
      <p className="muted">That page doesn’t exist. <Link to="/">Back to mogi</Link></p>
    </main>
  );
}

const router = createBrowserRouter([
  {
    element: <Root />,
    children: [
      { path: "/", element: <Home /> },
      { path: "/problems", element: <Problems /> },
      { path: "/problem/:corpus/:id", element: <Problem /> },
      { path: "/problem.html", element: <LegacyProblem /> },
      { path: "/problems.html", element: <Navigate to="/problems" replace /> },
      { path: "/index.html", element: <Navigate to="/" replace /> },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
