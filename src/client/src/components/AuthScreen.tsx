import { useState, type FormEvent } from "react";
import { register as registerRequest } from "../services/auth";

export interface AuthScreenProps {
  onLogin: (email: string, password: string) => Promise<void>;
}

export function AuthScreen({ onLogin }: AuthScreenProps): JSX.Element {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "register") {
        await registerRequest(email, password);
      }
      await onLogin(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <main className="panel rise-in w-full max-w-sm">
        <div className="mb-5 flex flex-col items-center gap-2 text-center">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-600 text-sm font-bold text-white shadow-panel">
            N
          </span>
          <h1 className="text-lg font-semibold text-white">
            {mode === "login" ? "Log in" : "Create account"}
          </h1>
          <p className="text-xs text-slate-500">Notely</p>
        </div>

        {error && (
          <p role="alert" className="alert-error mb-4">
            {error}
          </p>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-4" data-testid="auth-form">
          <label className="flex flex-col gap-1.5">
            <span className="field-label">Email</span>
            <input
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="text-input"
              placeholder="you@example.com"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="field-label">Password</span>
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="text-input"
              placeholder="••••••••"
            />
          </label>
          <button type="submit" disabled={submitting} className="btn-primary mt-1 w-full">
            {submitting ? "Please wait…" : mode === "login" ? "Log in" : "Register"}
          </button>
        </form>

        <button
          type="button"
          onClick={() => setMode(mode === "login" ? "register" : "login")}
          className="mt-4 w-full text-center text-sm text-brand-300 hover:text-brand-200"
        >
          {mode === "login" ? "Need an account? Register" : "Have an account? Log in"}
        </button>
      </main>
    </div>
  );
}
