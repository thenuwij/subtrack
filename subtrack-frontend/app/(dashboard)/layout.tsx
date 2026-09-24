import Navbar from '@/components/layout/Navbar'
import { CurrencyProvider } from '@/lib/context/currency'
import { Toaster } from '@/components/ui/sonner'
import { AgentChat } from '@/components/agent/AgentChat'
import { AgentPageContextProvider } from '@/lib/agent/page-context'
import { ApiCacheProvider } from '@/components/providers/ApiCacheProvider'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <CurrencyProvider>
      <ApiCacheProvider>
      <AgentPageContextProvider>
        <div className="flex min-h-screen">
          <Navbar />
          <main className="min-w-0 flex-1 overflow-auto bg-background pb-20 pt-14 md:pb-0 md:pt-0">
            {children}
          </main>
          <AgentChat />
        </div>
      </AgentPageContextProvider>
      </ApiCacheProvider>
      <Toaster />
    </CurrencyProvider>
  )
}
