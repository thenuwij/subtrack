/**
 * Supabase auth errors, rewritten for people.
 *
 * The raw messages are written for developers ("Invalid login credentials")
 * or leak configuration detail ("Signups not allowed for this instance").
 * Anything unrecognised falls through to a generic line rather than showing
 * an internal string.
 */

/** Deliberately identical for a wrong password and an unknown email, so the
 *  form cannot be used to discover which addresses have accounts. */
const WRONG_CREDENTIALS = 'That email or password is not right.'

const PATTERNS: ReadonlyArray<[RegExp, string]> = [
  [/invalid login credentials/i, WRONG_CREDENTIALS],
  [/email not confirmed/i,
    'Confirm your email first — check your inbox for the link we sent.'],
  [/already registered|already exists/i,
    'An account with that email already exists. Sign in instead.'],
  [/password should be at least (\d+)/i,
    'Use a longer password — at least $1 characters.'],
  [/weak.?password|password.*(too weak|requirements)/i,
    'Choose a stronger password.'],
  [/rate limit|too many requests/i,
    'Too many attempts. Wait a minute, then try again.'],
  [/signups? (not allowed|disabled)/i,
    'Email sign-up is not enabled for this project yet.'],
  [/email logins are disabled|email provider.*disabled/i,
    'Email sign-in is not enabled for this project yet.'],
  [/token has expired|invalid.*token|expired/i,
    'That link has expired. Request a new one.'],
  [/same.?password|should be different/i,
    'Choose a password you have not used here before.'],
  [/failed to fetch|network/i,
    'Could not reach the sign-in service. Check your connection.'],
]

export function authErrorMessage(error: unknown, fallback: string): string {
  const raw = error instanceof Error ? error.message : ''
  if (!raw) return fallback
  for (const [pattern, message] of PATTERNS) {
    const match = raw.match(pattern)
    if (match) return message.replace('$1', match[1] ?? '')
  }
  return fallback
}

/** Supabase's own minimum is 6; this is the app's stricter floor. Checked in
 *  the browser purely for fast feedback — Supabase remains the real gate. */
export const MIN_PASSWORD_LENGTH = 8

export function passwordProblem(password: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH) {
    return `Use at least ${MIN_PASSWORD_LENGTH} characters.`
  }
  return null
}
