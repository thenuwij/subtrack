import Navbar from '@/components/layout/Navbar'
import { CurrencyProvider } from '@/lib/context/currency'
import { Toaster } from '@/components/ui/sonner'
import { AgentChat } from '@/components/agent/AgentChat'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <CurrencyProvider>
      <div className="flex min-h-screen">
        <Navbar />
        <main className="min-w-0 flex-1 overflow-auto bg-background pb-20 pt-14 md:pb-0 md:pt-0">
          {children}
        </main>
        <AgentChat />
      </div>
      <Toaster />
    </CurrencyProvider>
  )
}
