import { XIcon } from 'lucide-react'

import { useErrorFeed } from '@/hooks/useErrorFeed'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'

/** A notice's age, coarsely: what a person needs to tell "just now" from "earlier". */
function ago(iso: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`
  return new Date(iso).toISOString().slice(11, 19)
}

/**
 * The layout's error tray: the last few operational failures from this
 * browser's pipeline runs, newest on top, each dismissible. Rendered by
 * AppLayout outside the page outlet, so it survives navigation. Draws nothing
 * while there is nothing to say.
 */
export function ErrorTray() {
  const { notices, dismiss } = useErrorFeed()
  if (notices.length === 0) return null

  return (
    <div
      role="region"
      aria-label="Errors"
      className="fixed right-4 top-16 z-50 flex w-[min(28rem,calc(100vw-2rem))] flex-col gap-2"
    >
      {notices.map((notice) => (
        <Alert key={notice.id} variant="destructive" className="bg-background shadow-md">
          <AlertTitle className="flex items-center justify-between gap-2">
            <span>
              {notice.app} · {notice.source}
            </span>
            <span className="flex items-center gap-2 text-xs font-normal">
              {ago(notice.timestamp)}
              <Button
                variant="ghost"
                size="icon"
                className="size-6"
                aria-label="Dismiss"
                onClick={() => dismiss(notice.id)}
              >
                <XIcon className="size-3.5" />
              </Button>
            </span>
          </AlertTitle>
          <AlertDescription className="flex flex-col gap-1">
            <span>{notice.message}</span>
            {notice.detail && <span className="font-mono text-xs break-all">{notice.detail}</span>}
            {notice.request_id && (
              <span className="text-xs opacity-70">request {notice.request_id.slice(0, 8)}</span>
            )}
          </AlertDescription>
        </Alert>
      ))}
    </div>
  )
}
