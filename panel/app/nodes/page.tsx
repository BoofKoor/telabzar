'use client'

import { C } from '@/lib/theme'
import { usePageData, type NodesPage } from '@/lib/api'
import { Shell } from '@/components/Shell'
import { Section } from '@/components/Section'
import { PageState } from '@/components/ApiBanner'
import { Btn, Chip, Cmd, Flag, Head, Input, Row, Select } from '@/components/ui'

/**
 * ۰۴ NODES — ماشین‌های راه‌دور روی WireGuard.
 *
 * سه نقش، و تفاوتشان روی صفحه دیده می‌شود چون رفتارِ عملیاتی‌شان فرق دارد:
 * `download` و `processing` ورکرِ ARQ‌اند (صف دارند)، ولی `gateway` یک
 * پروکسیِ معکوس است و اصلاً صف ندارد — کارتی که هر سه را یک‌شکل نشان بدهد
 * این تفاوت را پنهان می‌کند.
 *
 * فرمانِ نصب یک توکنِ **یک‌بارمصرف** دارد، پس بعد از نمایش دیگر تکرارشدنی
 * نیست؛ به‌همین دلیل جعبه‌اش کنارِ خودِ فرم است نه پشتِ یک ریدایرکت.
 */
export default function Page() {
  const state = usePageData<NodesPage>('nodes')
  const rows = state.data?.rows ?? []
  const up = rows.filter((n) => n.up).length

  return (
    <Shell active="04" cmd="./ctl nodes --status" bits={false}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Chip color={rows.length && up === rows.length ? C.acc : C.bad}>
          {up}/{rows.length} up
        </Chip>
        <Chip>wg0 {state.data?.wg.subnet ?? '—'}</Chip>
        <Chip>master {state.data?.wg.master ?? '—'}</Chip>
        <span style={{ marginLeft: 'auto', fontSize: 9.5, color: C.inkDim, letterSpacing: '.1em' }}>
          peers are declarative · host wg-sync reconciles from the Node table
        </span>
      </div>

      <Section label="NODES" sigil="⎔" right="heartbeat ttl 45s" corners pad="22px 14px 12px">
        <PageState state={state}>
          <Head
            cols={[
              { w: 46, label: '' },
              { w: 108, label: 'NAME' },
              { w: 100, label: 'ROLE' },
              { w: 100, label: 'WG IP' },
              { w: 56, label: 'JOBS', right: true },
              { w: 78, label: 'DONE', right: true },
              { label: 'VERSION', right: true },
            ]}
          />
          {rows.map((n, i) => (
            <Row key={n.id} last={i === rows.length - 1}>
              <Flag text={n.up ? '[ UP ]' : '[DOWN]'} color={n.up ? C.acc : C.bad} />
              <span style={{ width: 108, color: C.inkHi }}>{n.name}</span>
              <span style={{ width: 100 }}>
                <Chip color={n.role === 'gateway' ? C.violet : C.info}>{n.role}</Chip>
              </span>
              <span style={{ width: 100, color: C.inkLo }}>{n.ip}</span>
              <span style={{ width: 56, textAlign: 'right', color: n.jobs ? C.acc : C.inkFaint }}>{n.jobs}</span>
              <span style={{ width: 78, textAlign: 'right', color: C.inkLo }}>
                {n.done.toLocaleString('en-US')}
              </span>
              <span style={{ flex: 1, textAlign: 'right', color: n.up ? C.inkDim : C.bad }}>
                {n.up ? n.ver : 'offline'}
              </span>
            </Row>
          ))}
          {!rows.length && (
            <div style={{ padding: '18px 0', textAlign: 'center', color: C.inkFaint, fontSize: 10.5, lineHeight: 1.9 }}>
              NO NODES — standalone master
              <br />
              <span style={{ fontSize: 9.5 }}>every path runs here; nothing is degraded by this</span>
            </div>
          )}
        </PageState>
        <div style={{ marginTop: 10, fontSize: 9.5, color: C.inkDim, lineHeight: 1.8 }}>
          a dead node is never a broken path: downloads fall back to arq:queue:dl:master, heavy ops
          stay on the master queue, and links revert to public_base.
        </div>
      </Section>

      <div className="mx-duo" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 18 }}>
        {/* فرم مستقیم به هندلرِ موجودِ Jinja POST می‌کند و همان ریدایرکت را
            می‌گیرد. توکنِ **یک‌بارمصرف** بعد از join مصرف می‌شود و دوباره
            نمایش‌دادنی نیست، پس صفحهٔ نتیجه جای نمایشش است نه این‌جا. */}
        <Section label="ADD NODE" sigil="✚" right="one-time token · 30 min" pad="22px 14px 12px">
          <form method="post" action="/nodes/add">
            <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
              <Input name="name" placeholder="name (e.g. dl-ams)" style={{ width: 170 }} />
              <Select name="role" defaultValue={state.data?.roles[0] ?? 'download'} style={{ width: 140 }}>
                {(state.data?.roles ?? []).map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </Select>
              <Btn type="submit" solid>
                ISSUE
              </Btn>
            </div>
          </form>
          {state.data && !state.data.master_ready && (
            <div style={{ fontSize: 10, color: C.warn, lineHeight: 1.9 }}>
              master WG is not provisioned yet — run{' '}
              <span style={{ color: C.accHi }}>telabzar nodes-enable</span> on the host first, or the
              token will have nothing to join.
            </div>
          )}
          <div style={{ marginTop: 9, fontSize: 9.5, color: C.inkDim, lineHeight: 1.8 }}>
            the install command is shown once, on the page that follows — the token is consumed on
            join (redis GETDEL) and cannot be re-displayed.
          </div>
        </Section>

        <Section label="WG MESH" sigil="⌸" right={`${state.data?.wg.master ?? '—'} · master`} pad="22px 14px 12px">
          <pre style={{ fontFamily: 'inherit', fontSize: 11, lineHeight: 2, color: C.inkLo }}>
            {`master ${state.data?.wg.master ?? '—'}`}
            {rows.map((n, i) => (
              <span key={n.id}>
                {`\n       ${i === rows.length - 1 ? '└─' : '├─'} `}
                <span style={{ color: n.up ? C.acc : C.bad }}>{n.name.padEnd(10)}</span>
                {`${n.ip}  ${n.up ? 'up' : 'down'}`}
              </span>
            ))}
            {!rows.length && '\n       (no peers)'}
          </pre>
          <div
            style={{
              borderTop: `1px solid ${C.edgeHair}`,
              marginTop: 11,
              paddingTop: 10,
              fontSize: 10,
              color: C.inkDim,
              lineHeight: 1.9,
            }}
          >
            {rows.length} peer{rows.length === 1 ? '' : 's'} configured · subnet{' '}
            <span style={{ color: C.inkMid }}>{state.data?.wg.subnet ?? '—'}</span>
            <br />
            orphan jobs reaped back to master:{' '}
            <span style={{ color: state.data?.reaped ? C.warn : C.acc }}>{state.data?.reaped ?? 0}</span>
          </div>
        </Section>
      </div>

      <Section
        label="AFTER A CODE CHANGE" sigil="⚠"
        labelColor={C.warn}
        edge={C.auditEdge}
        bg={C.auditBg}
        right="telabzar update is not enough"
        rightColor={C.warn}
        pad="22px 14px 12px"
      >
        <div style={{ fontSize: 10.5, color: C.ink, lineHeight: 1.9, marginBottom: 9 }}>
          a node runs its own separately-built image, so a fix to run_download / run_op / gateway_node
          does not reach it until that image is rebuilt on the node host:
        </div>
        <Cmd>{`cd /opt/telabzar-node/repo && sudo git pull && sudo bash node/update.sh`}</Cmd>
      </Section>
    </Shell>
  )
}
