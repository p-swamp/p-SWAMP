import { WifiOffIcon } from 'lucide-react'

// This page's own pieces, imported relatively so the folder stays self-contained.
import { useReferenceSubappSocket } from './useReferenceSubappSocket'
import { Alert, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardAction,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

/**
 * The Reference example page (route `/reference-subapp`) — a thin renderer over
 * useReferenceSubappSocket: the buttons POST commands, the server owns the count and
 * pushes it back down the socket, and this component only renders what it is
 * handed.
 */
export function ReferenceSubappPage() {
  const { state, status, connected, bump, reset } = useReferenceSubappSocket()

  return (
    <Card className="w-full max-w-xl gap-0">
      <CardHeader className="border-b">
        <CardTitle className="text-lg">Reference example</CardTitle>
        <span className="text-gray-500">
          Used for end to end tests of our client-server stack. When we refactor or upgrade the project, we use this page as a smoketest to see if anything fundamental breaks.
         <em> Do not use this page to do p-SWAMP experiments; use <code>pswamp new subapp</code> to generate a new
          page/subapp instead. 🙂</em>
    </span>
        <CardAction className="self-center">
          {connected ? (
            <Badge variant="default">Online</Badge>
          ) : (
            <Badge variant="outline" className="text-muted-foreground">
              <WifiOffIcon className="size-3" />
              Offline
            </Badge>
          )}
        </CardAction>
      </CardHeader>

      <CardContent className="px-6 py-0">
        {/* The server-owned state, or the status banner in its place. */}
        <div className="flex min-h-[152px] items-center justify-center">
          {connected && state ? (
            <span role="status" aria-label="Bump count" className="text-6xl font-bold tabular-nums">
              {state.count}
            </span>
          ) : (
            <Alert
              variant={status.kind === 'offline' && status.isError ? 'destructive' : 'default'}
              className="w-auto"
            >
              <AlertTitle>
                {status.kind === 'online' ? 'Waiting for state…' : status.label}
              </AlertTitle>
            </Alert>
          )}
        </div>
      </CardContent>

      <CardFooter className="flex-col gap-4 border-t pt-6">
        {/* Disabled until connected. The commands are POSTs and would in fact
            reach the server without a socket — but the result comes back *on*
            the socket, so a click with none open would appear to do nothing. */}
        <div className="flex items-center justify-center gap-2">
          <Button disabled={!connected} onClick={bump}>
            Bump
          </Button>
          <Button variant="outline" disabled={!connected} onClick={reset}>
            Reset
          </Button>
        </div>
      </CardFooter>
    </Card>
  )
}
