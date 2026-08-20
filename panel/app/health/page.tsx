'use client'

import { C } from '@/lib/theme'
import { DL_RATE, ENGINES, STUCK } from '@/lib/pages'
import { Shell } from '@/components/Shell'
import { Section } from '@/components/Section'
import { Queue } from '@/components/Sidebar'
import { Bar, Chip, Flag, Head, Row } from '@/components/ui'
import { hueOf } from '@/lib/zones'

/**
 * ۰۳ HEALTH — «الان چه چیزی خراب است؟»
 *
 * مرزِ این صفحه با TRAFFIC عمدی است و در §۷ ثبت شده: این‌جا **لحظه‌ای** است
 * و آن‌جا **تاریخی**. پس هیچ نمودارِ روندی این‌جا نیست و هیچ سرویسی آن‌جا.
 *
 * دو کارت که در پنلِ فارسی هم هستند و این‌جا هم ماندند چون دقیقاً همان
 * سؤال‌های عملیاتی‌اند: نسخهٔ موتور (کهنه = «سشن را عوض نکن، آپدیت کن») و
 * جاب‌های گیرکرده (که Open Questions هنوز بازش می‌داند).
 */
export default function Page() {
  const services = [
    { name: 'postgres', meta: '4ms · 38 conn · 16.13', flag: '[ OK ]', color: C.acc },
    { name: 'redis', meta: '1ms · 12,408 keys', flag: '[ OK ]', color: C.acc },
    { name: 'local-bot-api', meta: '12ms · local mode · 2GB cap', flag: '[ OK ]', color: C.acc },
    { name: 'pot-provider', meta: '88ms · bgutil 1.3.1 · up 6d', flag: '[ OK ]', color: C.acc },
    { name: 'gateway', meta: 'range ok · :2096 · faststart', flag: '[ OK ]', color: C.acc },
    { name: 'clamav', meta: 'daily.cvd 27311 updating', flag: '[WARN]', color: C.warn },
  ]

  return (
    <Shell active="03" cmd="./ctl health --watch">
      {({ vals }) => (
        <>
          <div className="mx-trio" style={{ display: 'grid', gridTemplateColumns: 'repeat(3,minmax(0,1fr))', gap: 18 }}>
            <Section label="SERVICES" sigil="◉" right="6 checked" corners pad="22px 14px 11px">
              {services.map((s, i) => (
                <Row key={s.name} last={i === services.length - 1}>
                  <Flag text={s.flag} color={s.color} />
                  <span style={{ color: C.inkMid }}>{s.name}</span>
                  <span style={{ marginLeft: 'auto', color: C.inkLo, fontSize: 10 }}>{s.meta}</span>
                </Row>
              ))}
            </Section>

            <Queue queues={vals.queueRows} resources={vals.resources} />

            <Section label="DISK · /work" sigil="▤" right="412/900 GB" pad="22px 14px 12px">
              <div style={{ display: 'flex', flexDirection: 'column', gap: 9, fontSize: 11 }}>
                {[
                  { k: 'used', v: '412 GB', pct: 46, c: C.acc },
                  { k: 'downloads', v: '188 GB', pct: 21, c: C.info },
                  { k: 'work tmp', v: '61 GB', pct: 7, c: C.violet },
                  { k: 'models', v: '3.4 GB', pct: 1, c: C.warn },
                ].map((r) => (
                  <div key={r.k} style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                    <span style={{ width: 74, color: C.ink }}>{r.k}</span>
                    <Bar pct={r.pct} color={r.c} />
                    <span style={{ marginLeft: 'auto', color: C.inkHi }}>{r.v}</span>
                  </div>
                ))}
              </div>
              <div
                style={{
                  borderTop: `1px solid ${C.edgeHair}`,
                  marginTop: 11,
                  paddingTop: 10,
                  fontSize: 10,
                  color: C.inkDim,
                  lineHeight: 1.8,
                }}
              >
                free 488 GB · dl_min_free_gb 20
                <br />
                model-cache volume mounted
              </div>
            </Section>
          </div>

          <div className="mx-duo" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 18 }}>
            <Section label="DOWNLOAD RATE · TODAY (UTC)" sigil="↓" right="dlstat:*" pad="22px 14px 12px">
              <Head cols={[{ w: 92, label: 'PLATFORM' }, { label: 'OK' }, { w: 88, label: 'OK / N', right: true }]} />
              {DL_RATE.map((d, i) => {
                const n = d.ok + d.fail
                const pct = Math.round((d.ok / n) * 100)
                const col = pct >= 90 ? C.acc : pct >= 75 ? C.warn : C.bad
                return (
                  <Row key={d.platform} last={i === DL_RATE.length - 1}>
                    <span style={{ width: 92, color: hueOf(d.platform) }}>{d.platform}</span>
                    <span style={{ flex: 1 }}>
                      <Bar pct={pct} width={16} color={col} />
                    </span>
                    <span style={{ width: 88, textAlign: 'right', color: col, whiteSpace: 'nowrap' }}>
                      {pct}% · {d.ok}/{n}
                    </span>
                  </Row>
                )
              })}
              <div style={{ marginTop: 9, fontSize: 9.5, color: C.inkDim, letterSpacing: '.06em' }}>
                window = today UTC · dlstat TTL = 48h, so a raw KEYS scan double-counts
              </div>
            </Section>

            <Section label="ENGINE VERSIONS" sigil="⚙" right="dlver:*" pad="22px 14px 12px">
              <Head cols={[{ w: 82, label: 'WHO' }, { w: 78, label: 'GALLERY-DL' }, { label: 'YT-DLP' }, { w: 58, label: '', right: true }]} />
              {ENGINES.map((e, i) => (
                <Row key={e.who} last={i === ENGINES.length - 1}>
                  <span style={{ width: 82, color: C.inkMid }}>{e.who}</span>
                  <span style={{ width: 78, color: e.fresh ? C.inkLo : C.warn }}>{e.gdl}</span>
                  <span style={{ flex: 1, color: e.fresh ? C.inkLo : C.warn }}>{e.ytdlp}</span>
                  <span style={{ width: 58, textAlign: 'right' }}>
                    {e.fresh ? (
                      <Chip color={C.acc}>fresh</Chip>
                    ) : (
                      <Chip color={C.warn} border="#3A2E14">
                        stale
                      </Chip>
                    )}
                  </span>
                </Row>
              ))}
              <div style={{ marginTop: 10, fontSize: 10, color: C.inkDim, lineHeight: 1.8 }}>
                stale engine → <span style={{ color: C.accHi }}>node/update.sh</span> on that host.
                <br />
                current engine + login errors → replace the session, not the code.
              </div>
            </Section>
          </div>

          <Section
            label="STUCK JOBS" sigil="⏳"
            labelColor={C.warn}
            edge={C.auditEdge}
            bg={C.auditBg}
            right="age &gt; job_timeout"
            rightColor={C.warn}
            pad="22px 14px 12px"
          >
            <Head cols={[{ w: 56, label: 'ID' }, { w: 96, label: 'OP' }, { w: 76, label: 'STATUS' }, { w: 90, label: 'AGE' }, { label: 'FILE' }]} />
            {STUCK.map((j, i) => (
              <Row key={j.id} last={i === STUCK.length - 1}>
                <span style={{ width: 56, color: C.inkDim }}>#{j.id}</span>
                <span style={{ width: 96, color: C.accHi }}>{j.op}</span>
                <span style={{ width: 76, color: j.status === 'running' ? C.warn : C.inkDim }}>{j.status}</span>
                <span style={{ width: 90, color: C.bad }}>{j.age}</span>
                <span style={{ flex: 1, color: C.inkLo, overflow: 'hidden', textOverflow: 'ellipsis' }}>{j.file}</span>
              </Row>
            ))}
            <div style={{ marginTop: 10, fontSize: 10, color: C.inkDim, lineHeight: 1.8 }}>
              `finally` does not run on SIGKILL, so a worker killed between `status=running` and its
              commit leaves the row forever. Nothing sweeps these today — Open Questions.
            </div>
          </Section>
        </>
      )}
    </Shell>
  )
}
