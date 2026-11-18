import { Badge } from '@/components/ui/badge'
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

import { useStateEstimatorSocket } from './useStateEstimatorSocket'

/** The State Estimator page (route `/state-estimator`): the module's latest result. */
export function StateEstimatorPage() {
  const { state, connected } = useStateEstimatorSocket()
  const result = state?.result?.result

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>State Estimator</CardTitle>
        <CardAction>
          <Badge variant={connected ? 'default' : 'outline'}>{connected ? 'Online' : 'Offline'}</Badge>
        </CardAction>
      </CardHeader>
      <CardContent>
        {result ? (
          <div className="text-2xl tabular-nums" data-testid="result">
            {result.frequency_hz.toFixed(3)} Hz <span className="text-gray-500">at {result.station}</span>
          </div>
        ) : (
          <div className="text-gray-500">Waiting for the first result…</div>
        )}
      </CardContent>
    </Card>
  )
}
