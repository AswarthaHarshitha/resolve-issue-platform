/**
 * Token storage decision (DECISIONS.md D27): the JWT access token is stored
 * in localStorage and sent via the `Authorization: Bearer` header. This is
 * the standard SPA/JWT pattern - it keeps the backend fully stateless (no
 * cookie/CORS-credentials configuration, no CSRF token plumbing) and lets
 * the same client code work identically in a browser or any other HTTP
 * client.
 *
 * This is NOT immune to XSS: a successful script injection on this origin
 * could read localStorage and exfiltrate the token, valid until it expires
 * (JWT_ACCESS_TOKEN_EXPIRE_MINUTES, 60 min by default). A hardened
 * production deployment would move the token into an httpOnly, Secure,
 * SameSite=strict cookie set by the backend, paired with CSRF protection -
 * trading this simplicity for real XSS resistance. That tradeoff is
 * intentionally deferred rather than pretending this MVP is immune to it.
 */

const TOKEN_KEY = "resolve.access_token";

export function getStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setStoredToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // localStorage can be unavailable (private browsing, blocked storage).
    // The session just won't persist across reloads - a degraded
    // experience, not a crash.
  }
}

export function clearStoredToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Nothing to clean up if storage was never reachable to begin with.
  }
}
