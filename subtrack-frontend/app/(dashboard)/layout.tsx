import Navbar from '@/components/layout/Navbar'
import { CurrencyProvider } from '@/lib/context/currency'
import { Toaster } from '@/components/ui/sonner'
import { AgentChat } from '@/components/agent/AgentChat'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <CurrencyProvider>
      <div className="flex min-h-screen">
        <Navbar />
        <main className="flex-1 bg-background overflow-auto">
          {children}
        </main>
        <AgentChat />
      </div>
      <Toaster />
    </CurrencyProvider>
  )
}