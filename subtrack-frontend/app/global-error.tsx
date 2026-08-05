'use client'

import { useEffect } from 'react'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('Subtrack root error', error)
  }, [error])

  return (
    <html lang="en">
      <body style={{ margin: 0, background: '#f7f7f8', color: '#18181b', fontFamily: 'system-ui, sans-serif' }}>
        <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 24 }}>
          <div style={{ width: '100%', maxWidth: 420, textAlign: 'center' }}>
            <p style={{ color: '#6d5bd0', fontWeight: 700 }}>Subtrack</p>
            <h1 style={{ fontSize: 28, marginBottom: 8 }}>We couldn&apos;t load the app</h1>
            <p style={{ color: '#62626b', lineHeight: 1.5 }}>
              Your payment data is safe. Try loading Subtrack again.
            </p>
            <button
              type="button"
              onClick={reset}
              style={{
                marginTop: 16,
                border: 0,
                borderRadius: 8,
                background: '#6d5bd0',
                color: 'white',
                padding: '10px 16px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Try again
            </button>
          </div>
        </main>
      </body>
    </html>
  )
}
