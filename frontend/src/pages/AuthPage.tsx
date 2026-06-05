import { type FormEvent, useState } from "react";
import { useAuth } from "../contexts/AuthContext";

export function AuthPage() {
  const { authError, setAuthError, loginUser, registerUser } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setAuthError("");
    setSubmitting(true);
    try {
      if (mode === "login") {
        await loginUser(username, password);
      } else {
        await registerUser(username, password);
      }
    } catch (err) {
      setAuthError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-page__bg" aria-hidden="true" />
      <div className="auth-card">
        <div className="auth-card__brand">
          <h1>Fitness Coach</h1>
          <p>AI coaching assistant — sign in to continue</p>
        </div>

        <div className="tab-group">
          <button
            type="button"
            className={mode === "login" ? "tab tab--active" : "tab"}
            onClick={() => setMode("login")}
          >
            Sign in
          </button>
          <button
            type="button"
            className={mode === "register" ? "tab tab--active" : "tab"}
            onClick={() => setMode("register")}
          >
            Register
          </button>
        </div>

        <form onSubmit={onSubmit} className="auth-form">
          <label className="field">
            <span>Username</span>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Enter username"
              autoComplete="username"
              required
              minLength={3}
            />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
              minLength={8}
            />
          </label>
          <button type="submit" className="auth-form__submit" disabled={submitting}>
            {submitting ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
          {authError ? <p className="alert alert--error">{authError}</p> : null}
        </form>
      </div>
    </div>
  );
}
