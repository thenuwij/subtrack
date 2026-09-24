'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'

export function UserAvatar({
  name,
  email,
  avatarUrl,
  className,
}: {
  name: string
  email?: string
  avatarUrl?: string
  className?: string
}) {
  const [failed, setFailed] = useState(false)
  const initials = (name || email || '?')
    .split(/[\s@.]+/)
    .filter(Boolean)
    .map(part => part[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)

  if (avatarUrl && !failed) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={avatarUrl}
        alt=""
        onError={() => setFailed(true)}
        className={cn('shrink-0 rounded-full object-cover', className)}
      />
    )
  }

  return (
    <span
      aria-hidden="true"
      className={cn(
        'flex shrink-0 items-center justify-center rounded-full bg-primary/15 font-semibold text-primary',
        className,
      )}
    >
      {initials}
    </span>
  )
}
