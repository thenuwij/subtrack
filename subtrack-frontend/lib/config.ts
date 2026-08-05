const configuredApiUrl = process.env.NEXT_PUBLIC_API_URL

if (process.env.NODE_ENV === 'production') {
  if (!configuredApiUrl) {
    throw new Error('NEXT_PUBLIC_API_URL must be configured for production builds.')
  }
  const parsed = new URL(configuredApiUrl)
  const hostname = parsed.hostname.toLowerCase()
  if (
    parsed.protocol !== 'https:'
    || hostname === 'localhost'
    || hostname === '127.0.0.1'
    || hostname === '::1'
    || hostname.endsWith('.localhost')
    || parsed.username
    || parsed.password
    || (parsed.pathname !== '' && parsed.pathname !== '/')
    || parsed.search
    || parsed.hash
  ) {
    throw new Error('NEXT_PUBLIC_API_URL must be an HTTPS origin in production.')
  }
}

export const API_URL = (configuredApiUrl || 'http://127.0.0.1:8000').replace(/\/$/, '')
