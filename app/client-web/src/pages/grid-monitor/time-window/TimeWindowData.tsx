import { type ReactNode, useEffect, useMemo } from 'react'

import { TimeWindowContext } from './timeWindowContext'
import { useChannelCatalogue } from './useChannelCatalogue'
import { useTimeWindowSocket } from './useTimeWindowSocket'

/**
 * Opens the time-window socket once and asks it for one whole measurement.
 *
 * The server's opening selection is eight channels picked to show the recorded
 * disturbance, which suits a chart with a legend. The main window wants what the
 * Qt frequency dock plots — **every** station's frequency — so this selects
 * all channels of `measurement` once the socket is up.
 *
 * It waits for the first message rather than for the socket to open: a command
 * is a POST, which needs the server to have registered this view, and the
 * message is what proves it has. A reconnect starts over with the server's
 * default, so the selection is re-applied whenever what is shown is not what was
 * asked for — which also makes it self-correcting, with nothing to remember.
 */
export function TimeWindowData({
  measurement,
  children,
}: {
  measurement: string
  children: ReactNode
}) {
  const { buffer, subscribe, channels, samplingRate, status, connected, selectChannels } =
    useTimeWindowSocket()
  const catalogue = useChannelCatalogue()

  const wanted = useMemo(
    () =>
      catalogue.channels
        .filter((channel) => channel.measurement === measurement)
        .map((channel) => channel.idx),
    [catalogue.channels, measurement],
  )
  const ready =
    connected &&
    wanted.length > 0 &&
    channels.length === wanted.length &&
    channels.every((channel, i) => channel.idx === wanted[i])

  useEffect(() => {
    if (connected && channels.length > 0 && wanted.length > 0 && !ready) {
      selectChannels(wanted)
    }
  }, [connected, channels, wanted, ready, selectChannels])

  const value = useMemo(
    () => ({
      buffer,
      subscribe,
      channels,
      samplingRate,
      status,
      connected,
      selectChannels,
      ready,
    }),
    [buffer, subscribe, channels, samplingRate, status, connected, selectChannels, ready],
  )
  return <TimeWindowContext value={value}>{children}</TimeWindowContext>
}
