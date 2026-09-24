import { ImageResponse } from 'next/og'

export const size = { width: 180, height: 180 }
export const contentType = 'image/png'

export default function AppleIcon() {
  const bar = (width: number, opacity: number) => (
    <div
      style={{
        width,
        height: 20,
        borderRadius: 10,
        background: '#ffffff',
        opacity,
      }}
    />
  )

  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          background: '#0072ee',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: 12,
          paddingLeft: 41,
        }}
      >
        {bar(98, 1)}
        {bar(68, 0.75)}
        {bar(38, 0.5)}
      </div>
    ),
    size
  )
}
