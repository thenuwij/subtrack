import type { Metadata } from 'next'
import './globals.css'
import { Geist, Inter } from 'next/font/google'
import { cn } from "@/lib/utils"
import { ThemeProvider } from 'next-themes'

const geist = Geist({ subsets: ['latin'], variable: '--font-geist' })
const inter = Inter({ subsets: ['latin'], variable: '--font-sans' })

export const metadata: Metadata = {
  title: 'Subtrack — Recurring payment tracker',
  description: 'See every recurring payment, what it costs each month, and what changes over time.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={cn("font-sans", geist.variable, inter.variable)} suppressHydrationWarning>
      <body className="bg-background text-foreground antialiased">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          {children}
        </ThemeProvider>
      </body>
    </html>
  )
}
