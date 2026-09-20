import { Component, type ErrorInfo, type ReactNode } from "react";

export interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * No React error boundary existed anywhere in the client (docs/gaps.md
 * #33i) -- any unexpected render-time throw (a malformed API payload
 * feeding a `.map` over `undefined`, a bad Date parse, etc.) unmounted the
 * entire tree, leaving the user staring at a blank white screen with no
 * recovery path and no indication anything went wrong.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error("Unhandled render error", error, info.componentStack);
  }

  private handleReload = (): void => {
    window.location.reload();
  };

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-4 text-center">
          <p className="text-lg font-semibold text-white">Something went wrong.</p>
          <p className="max-w-sm text-sm text-slate-400">
            An unexpected error occurred. Reloading usually fixes this.
          </p>
          <button type="button" onClick={this.handleReload} className="btn-primary">
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
