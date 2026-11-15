import type { ReactNode } from 'react'

interface GlassPanelProps {
  title?: string
  action?: ReactNode
  children: ReactNode
  className?: string
}

export function GlassPanel({ title, action, children, className = '' }: GlassPanelProps) {
  return (
    <section className={`fs-glass rounded-xl ${className}`}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-white/5 px-4 py-3">
          {title ? (
            <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-300">
              {title}
            </h2>
          ) : (
            <span />
          )}
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}
