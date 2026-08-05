function requiredPublicSetting(value: string | undefined, name: string): string {
  if (!value) throw new Error(`${name} must be configured.`)
  return value
}

const supabaseUrl = requiredPublicSetting(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  'NEXT_PUBLIC_SUPABASE_URL',
)
const supabaseAnonKey = requiredPublicSetting(
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  'NEXT_PUBLIC_SUPABASE_ANON_KEY',
)

export { supabaseUrl, supabaseAnonKey }
