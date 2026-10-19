import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

import { useIslandingDetectionSocket } from './useIslandingDetectionSocket'

/** The Islanding detection page (route `/islanding-detection`): the module's latest
 *  result, its status, and its alarm while one is active. */
export function IslandingDetectionPage() {
  const { state, connected } = useIslandingDetectionSocket()
  const result = state?.result?.result
  const alarm = state?.alarm
  const alarmActive = alarm?.type === 'init'

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Islanding</CardTitle>
        <CardAction>
          <Badge variant={connected ? 'default' : 'outline'}>{connected ? 'Online' : 'Offline'}</Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-3">
        {result && (
          <div>
            Status:{' '}
            <Badge variant={result.status === 'OK' ? 'secondary' : 'destructive'} data-testid="status">
              {result.status}
            </Badge>
          </div>
        )}
        {alarm && (
          <Alert variant={alarmActive ? 'destructive' : 'default'} data-testid="alarm">
            <AlertTitle>{alarmActive ? 'Alarm active' : 'Alarm cleared'}</AlertTitle>
            <AlertDescription>
              {alarm.message} ({new Date(alarm.timestamp).toLocaleTimeString()})
            </AlertDescription>
          </Alert>
        )}
        {result ? (
          <div data-testid="result">
            {result.islands.length === 0 ? (
              <div className="text-2xl">No islands</div>
            ) : (
              <ul className="space-y-1">
                {result.islands.map((island, i) => (
                  <li key={i}>
                    <span className="font-medium">Island {i + 1}:</span>{' '}
                    <span className="text-gray-500">{island.join(', ')}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <div className="text-gray-500">Waiting for the first result…</div>
        )}
      </CardContent>
    </Card>
  )
}
