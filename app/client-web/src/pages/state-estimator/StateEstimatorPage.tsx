import { Badge } from '@/components/ui/badge'
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

import { useStateEstimatorSocket } from './useStateEstimatorSocket'

const fixed = (value: number | null | undefined, digits: number) => (value == null ? '–' : value.toFixed(digits))

/** The State Estimator page (route `/state-estimator`): the latest estimate, one row per station. */
export function StateEstimatorPage() {
  const { state, connected } = useStateEstimatorSocket()
  const estimate = state?.result?.result
  const buses = estimate?.buses ?? []

  return (
    <Card className="w-full max-w-3xl">
      <CardHeader>
        <CardTitle>State Estimator</CardTitle>
        <CardAction>
          <Badge variant={connected ? 'default' : 'outline'}>{connected ? 'Online' : 'Offline'}</Badge>
        </CardAction>
      </CardHeader>
      <CardContent>
        {estimate ? (
          <div data-testid="result">
            <div className="mb-2 text-sm text-gray-500">
              {estimate.measured} measured, {estimate.estimated} estimated, of {buses.length} stations
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Station</TableHead>
                  <TableHead className="text-right">V (kV)</TableHead>
                  <TableHead className="text-right">V (p.u.)</TableHead>
                  <TableHead className="text-right">Angle (°)</TableHead>
                  <TableHead className="text-right">P (MW)</TableHead>
                  <TableHead className="text-right">Q (Mvar)</TableHead>
                  <TableHead>Source</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody className="tabular-nums">
                {buses.map((bus) => (
                  <TableRow key={bus.mRID}>
                    <TableCell>{bus.station}</TableCell>
                    <TableCell className="text-right">{fixed(bus.v_kv, 1)}</TableCell>
                    <TableCell className="text-right">{fixed(bus.v_pu, 3)}</TableCell>
                    <TableCell className="text-right">{fixed(bus.angle_deg, 2)}</TableCell>
                    <TableCell className="text-right">{fixed(bus.p_mw, 1)}</TableCell>
                    <TableCell className="text-right">{fixed(bus.q_mvar, 1)}</TableCell>
                    <TableCell className="text-gray-500">{bus.source}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <div className="text-gray-500">Waiting for the first estimate…</div>
        )}
      </CardContent>
    </Card>
  )
}
