import Navbar from '@/components/layout/Navbar'
import { CurrencyProvider } from '@/lib/context/currency'
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <CurrencyProvider>
      <div className="flex min-h-screen">
        <Navbar />
        <main className="flex-1 bg-background overflow-auto">
          {children}
        </main>
      </div>
    </CurrencyProvider>
  )
}