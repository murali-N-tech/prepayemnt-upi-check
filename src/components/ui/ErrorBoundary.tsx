import React from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

interface State {
  error: Error | null;
}

/** Keeps one screen's crash from taking down the whole app.
 *
 * Without this, an unexpected API shape on any single page threw during
 * render and React unmounted everything — the user got a blank white page
 * with no header, no navigation and no way back.
 */
export class ErrorBoundary extends React.Component<
  { children: React.ReactNode; resetKey?: string },
  State
> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    // Navigating away from the broken screen clears the error.
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className="rounded-xl border border-danger/25 bg-danger/5 p-6 max-w-2xl">
        <div className="flex items-start gap-3">
          <AlertTriangle className="h-5 w-5 text-danger shrink-0 mt-0.5" />
          <div className="min-w-0">
            <h2 className="font-semibold text-ink">This screen could not be drawn</h2>
            <p className="mt-1.5 text-sm text-ink-muted leading-relaxed">
              Usually this means the server returned something the page did not
              expect — most often because the Python service is down, so a list
              came back as an error object. The rest of the app still works.
            </p>
            <pre className="mt-3 p-3 rounded-lg bg-inset border border-line text-xs text-ink-muted font-mono overflow-x-auto">
              {this.state.error.message}
            </pre>
            <button
              onClick={() => this.setState({ error: null })}
              className="mt-4 inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-line bg-surface text-sm text-ink hover:bg-raised transition"
            >
              <RotateCcw className="h-4 w-4" />
              Try again
            </button>
          </div>
        </div>
      </div>
    );
  }
}

export default ErrorBoundary;
