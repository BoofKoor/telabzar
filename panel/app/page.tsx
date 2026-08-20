'use client'

import { C } from '@/lib/theme'
import { Shell } from '@/components/Shell'
import { Hero, Posture } from '@/components/Hero'
import { Kpis } from '@/components/Kpis'
import { Pipeline } from '@/components/Pipeline'
import { Throughput } from '@/components/Throughput'
import { JobStream } from '@/components/JobStream'
import { Radar } from '@/components/Radar'
import { PlatformTable } from '@/components/PlatformTable'
import { WireMonitor } from '@/components/WireMonitor'
import { ActivityMap } from '@/components/ActivityMap'
import { Audit, Errors, FlagList, Queue, WgFooter } from '@/components/Sidebar'

/**
 * صفحهٔ OVERVIEW.
 *
 * چیدمان همان سه‌لایهٔ طرح است و ترتیبش معنا دارد: نوارِ اعداد → اسلبِ
 * کانونی کنارِ وضعیت → KPI → خطِ لوله، و بعد دو ستون (محتوای اصلی ۱fr و
 * ستونِ کناریِ ۳۴۰ پیکسلی) که هر کدام سکشن‌های خودشان را دارند.
 */
export default function Page() {
  return (
    <Shell active="01" cmd="./ctl watch --all --interval=3" ranges>
      {({ vals, setHover }) => (
        <>
          <div className="mx-duo" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 300px', gap: 18 }}>
            <Hero rangeLabel={vals.range} rows={vals.heroRows} sub={vals.heroSub} value={vals.heroValue} />
            <Posture />
          </div>

          <Kpis kpis={vals.kpis} />
          <Pipeline steps={vals.pipeline} />

          <div
            className="mx-grid"
            style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 340px', gap: 18, alignItems: 'start' }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 18, minWidth: 0 }}>
              <Throughput
                rangeLabel={vals.range}
                trend={vals.trend}
                peak={vals.trendPeak}
                avg={vals.trendAvg}
                axis={vals.axis}
                latSpark={vals.latSpark}
                latNow={vals.latNow}
              />

              <JobStream rows={vals.logRows} />

              <div
                className="mx-duo"
                style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 18 }}
              >
                <Radar
                  radar={vals.radar}
                  ticks={vals.ticks}
                  poly={vals.radarPoly}
                  prevPoly={vals.radarPrevPoly}
                  foot={vals.radarFoot}
                  footColor={vals.radarFootColor}
                  onHover={setHover}
                />
                <PlatformTable rows={vals.platformRows} />
              </div>

              <WireMonitor lines={vals.hexlines} />
              <ActivityMap heat={vals.heat} />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
              <Queue queues={vals.queueRows} resources={vals.resources} />
              <FlagList label="SERVICES" sigil="◉" rows={vals.services} />
              <FlagList label="COOKIE POOL" sigil="⌬" right="2 degraded" rightColor={C.warn} rows={vals.cookies} truncate />
              <FlagList label="NODES" sigil="⎔" rows={vals.nodes} footer={<WgFooter />} />
              <Errors rows={vals.errors} />
              <Audit rows={vals.audit} />
            </div>
          </div>
        </>
      )}
    </Shell>
  )
}
