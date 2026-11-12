import { useEffect, useMemo, useState } from 'react'

import { fetchJson, request } from '@/api/client'

type Bucket = '显著' | '不显著' | '样本不足'

type Review = {
  id: number
  数据集代次: number
  基准区间: string
  目标度量: string
  显著阈值: number
  实验组样本量: number
  对照组样本量: number
  样本量: number
  实验组转化数: number
  对照组转化数: number
  p值: number | null
  复核结论: Bucket
  判定说明: string
  数据集最近刷新: string
  复核时间: string
  延期状态: string
  延期至: string | null
  是否为历史: boolean
  历史原因: string
  可延期: boolean
}

type Comparison = {
  旧结论代次: number
  旧基准区间: string
  旧样本量: number | null
  旧复核结论: string
  新结论代次: number
  新基准区间: string
  新样本量: number | null
  新复核结论: string
  区间是否变化: boolean
  样本量不可相加: boolean
  说明: string
}

type Summary = {
  实验编号: string
  实验名称: string
  目标度量: string
  基准区间: string
  显著阈值: number
  分析数据集: string
  数据集最近刷新代次: number
  数据集最近刷新时间: string
  最小样本量: number
  当前结论: Review | null
  当前代次待复核: boolean
  当前代次需按新区间复核: boolean
  历史结论: Review[]
  全部结论: Review[]
  数据集代次列表: { 代次: number; 最近刷新: string; 是否最新: boolean }[]
  分档: Record<Bucket, Review[]>
  历史分档: Record<Bucket, Review[]>
  前后对比: Comparison | null
  延期提示: string
}

type OverviewRow = {
  id: number
  实验编号: string
  实验名称: string
  目标度量: string
  基准区间: string
  显著阈值: number
  分析数据集: string
  数据集最近刷新代次: number
  数据集最近刷新时间: string
  当前复核结论: string
  当前样本量: number | null
  历史结论数: number
  当前代次待复核: boolean
}

const BUCKETS: Bucket[] = ['显著', '不显著', '样本不足']
const BUCKET_COLOR: Record<Bucket, string> = {
  显著: '#12b76a',
  不显著: '#98a2b3',
  样本不足: '#d97706',
}

function ReviewCard({
  review,
  canDefer,
  onDefer,
  deferring,
}: {
  review: Review
  canDefer?: boolean
  onDefer?: () => void
  deferring?: boolean
}) {
  return (
    <article className="review-card" style={{ borderLeftColor: BUCKET_COLOR[review.复核结论] }}>
      <header className="review-card-head">
        <strong>{review.复核结论}</strong>
        <span className="review-meta">代次 {review.数据集代次} · {review.基准区间}</span>
      </header>
      <dl className="review-fields">
        <div><dt>目标度量</dt><dd>{review.目标度量 || '—'}</dd></div>
        <div><dt>显著阈值</dt><dd>{review.显著阈值}</dd></div>
        <div><dt>样本量</dt><dd>{review.样本量}</dd></div>
        <div><dt>实验组 样本/转化</dt><dd>{review.实验组样本量} / {review.实验组转化数}</dd></div>
        <div><dt>对照组 样本/转化</dt><dd>{review.对照组样本量} / {review.对照组转化数}</dd></div>
        <div><dt>p 值</dt><dd>{review.p值 ?? '未计算'}</dd></div>
        <div><dt>数据集最近刷新</dt><dd>{review.数据集最近刷新}</dd></div>
        <div><dt>复核时间</dt><dd>{review.复核时间}</dd></div>
        <div><dt>复核时间</dt><dd>{review.复核时间}</dd></div>
      </dl>
      <p className="review-note">{review.判定说明}</p>
      {review.是否为历史 && <p className="review-note history-note">{review.历史原因}</p>}
      {review.延期状态 === '已延期' && (
        <p className="review-note">已延期至 {review.延期至}，请按新区间重新提交复核</p>
      )}
      {canDefer && review.可延期 && onDefer && (
        <button className="btn" type="button" disabled={deferring} onClick={onDefer}>
          {deferring ? '提交中…' : '样本不足，申请延期'}
        </button>
      )}
    </article>
  )
}

export default function ExperimentReviewView() {
  const [rows, setRows] = useState<OverviewRow[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [generation, setGeneration] = useState<number | null>(null)
  const [message, setMessage] = useState('')
  const [errorMessage, setErrorMessage] = useState('')
  const [busy, setBusy] = useState('')
  const [showHistory, setShowHistory] = useState(true)

  async function loadOverview() {
    const payload = await fetchJson<{ items: OverviewRow[] }>('/api/experiment/review')
    setRows(payload.items ?? [])
    return payload.items ?? []
  }

  useEffect(() => {
    loadOverview()
      .then((items) => setSelectedId((current) => current ?? (items[0]?.id ?? null)))
      .catch((error: unknown) => {
        setErrorMessage(error instanceof Error ? error.message : '复核清单读取失败')
      })
  }, [])

  async function loadSummary(id: number) {
    const payload = await fetchJson<Summary>(`/api/experiment/${id}/review`)
    setSummary(payload)
    // 默认停在最新代次；切换实验时重置，避免沿用上一个实验的代次。
    setGeneration(payload.数据集最近刷新代次)
    return payload
  }

  useEffect(() => {
    if (selectedId == null) {
      setSummary(null)
      return
    }
    setMessage('')
    loadSummary(selectedId).catch((error: unknown) => {
      setErrorMessage(error instanceof Error ? error.message : '复核明细读取失败')
    })
  }, [selectedId])

  async function refreshAll() {
    await loadOverview()
    if (selectedId != null) {
      await loadSummary(selectedId)
    }
  }

  const activeGeneration = generation ?? summary?.数据集最近刷新代次 ?? 0
  const isLatestGeneration = summary != null && activeGeneration === summary.数据集最近刷新代次

  // 某代次的全部结论；与概览卡片分开取数，切换代次时概览不会跟着回退。
  const generationReviews = useMemo(
    () => (summary?.全部结论 ?? []).filter((item) => item.数据集代次 === activeGeneration),
    [summary, activeGeneration],
  )

  const generations = summary?.数据集代次列表 ?? []

  function reviewsOf(bucket: Bucket) {
    return generationReviews.filter((review) => review.复核结论 === bucket)
  }

  // 当前代次是否只有旧区间的结论（例如刚延期），此时提交按钮应提示按新区间重算。
  const currentWindow = summary?.基准区间
  const currentGenerationHasWindow = generationReviews.some((review) => review.基准区间 === currentWindow)

  async function submitReview() {
    if (selectedId == null || !summary) return
    // 复核始终针对数据集最近刷新代次，用当前概览里的基准区间；历史代次只读。
    setErrorMessage('')
    setBusy('submit')
    try {
      const response = await request(`/api/experiment/${selectedId}/review`, {
        method: 'POST',
        body: JSON.stringify({
          values: {
            数据集代次: summary.数据集最近刷新代次,
            基准区间: summary.基准区间,
          },
        }),
      })
      const payload = await response.json()
      if (!response.ok || !payload.ok) {
        throw new Error(payload.message || payload.detail || '复核提交失败')
      }
      setMessage(payload.message)
      await refreshAll()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '复核提交失败')
    } finally {
      setBusy('')
    }
  }

  async function defer() {
    if (selectedId == null || !summary || !summary.当前结论) return
    setErrorMessage('')
    setBusy('defer')
    try {
      const response = await request(`/api/experiment/${selectedId}/review/deferral`, {
        method: 'POST',
        body: JSON.stringify({
          values: {
            数据集代次: summary.当前结论.数据集代次,
            基准区间: summary.当前结论.基准区间,
          },
        }),
      })
      const payload = await response.json()
      if (!response.ok || !payload.ok) {
        throw new Error(payload.message || payload.detail || '延期申请失败')
      }
      setMessage(payload.message)
      await refreshAll()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '延期申请失败')
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="page" data-module="experiment-review">
      <header className="page-head">
        <div>
          <h2>分析实验复核</h2>
          <p className="page-desc">
            复核结论绑定「数据集代次 + 基准区间」。概览固定展示目标度量、基准区间、显著阈值与数据集最近刷新代次，
            结论按显著 / 不显著 / 样本不足分栏；数据集刷新后旧结论进入历史区，新结论按新代次重算。
          </p>
        </div>
        <div className="page-actions">
          <label className="filter-item">
            <span>选择实验</span>
            <select
              value={selectedId ?? ''}
              onChange={(event) => setSelectedId(Number(event.target.value))}
            >
              {rows.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.实验编号} · {row.实验名称}
                </option>
              ))}
            </select>
          </label>
          <button
            className="btn primary"
            type="button"
            disabled={busy !== '' || !isLatestGeneration}
            onClick={() => void submitReview()}
            title={isLatestGeneration ? '按数据集最近刷新代次提交复核' : '历史代次只读，请切换回最新代次'}
          >
            提交最新代次复核
          </button>
        </div>
      </header>

      {errorMessage && <p className="error-text">{errorMessage}</p>}
      {message && <p className="ok-text">{message}</p>}

      {/* 概览只读最新代次口径，切换代次不改变这里的数值 */}
      <div className="stat-row" data-sticky-overview>
        {[
          ['目标度量', summary?.目标度量 ?? '—'],
          ['基准区间', summary?.基准区间 ?? '—'],
          ['显著阈值', summary?.显著阈值 ?? '—'],
          ['数据集最近刷新代次', summary ? `代次 ${summary.数据集最近刷新代次}` : '—'],
          ['数据集最近刷新时间', summary?.数据集最近刷新时间 ?? '—'],
          ['最小样本量', summary ? `每组 ${summary.最小样本量}` : '—'],
        ].map(([label, value]) => (
          <article key={label} className="stat-card">
            <span className="stat-label">{label}</span>
            <strong className="stat-value">{value}</strong>
          </article>
        ))}
      </div>

      {summary && (
        <section className="review-panel">
          <div className="review-banner">
            <div>
              <strong>{summary.实验编号} · {summary.实验名称}</strong>
              <p className="page-desc">
                分析数据集 {summary.分析数据集} · 数据集最近刷新代次 {summary.数据集最近刷新代次}
              </p>
            </div>
            <div className="generation-tabs">
              {generations.map((item) => (
                <button
                  key={item.代次}
                  type="button"
                  className={`btn ${item.代次 === activeGeneration ? 'primary' : ''}`}
                  onClick={() => setGeneration(item.代次)}
                >
                  代次 {item.代次}{item.是否最新 ? '（最新）' : ''}
                  <span className="generation-time">{item.最近刷新}</span>
                </button>
              ))}
            </div>
          </div>

          {isLatestGeneration && (summary.当前代次待复核 || summary.当前代次需按新区间复核) && (
            <p className="warn-banner">{summary.延期提示 || '当前代次尚未复核，请提交复核'}</p>
          )}
          {!isLatestGeneration && (
            <p className="info-banner">
              正在查看历史代次 {activeGeneration} 的结论，只读；最新的代次为 {summary.数据集最近刷新代次}。
            </p>
          )}
          {isLatestGeneration && !currentGenerationHasWindow && summary.基准区间 && (
            <p className="info-banner">
              代次 {activeGeneration} 在该区间还没有结论；提交复核会按基准区间 {summary.基准区间} 重算，
              已有区间 {summary.全部结论.filter((item) => item.数据集代次 === activeGeneration).map((item) => item.基准区间).join('、') || '无'} 的结论保留为历史对比。
            </p>
          )}

          {isLatestGeneration && summary.前后对比 && (
            <div className="compare-panel">
              <h3>结论前后对比</h3>
              <table className="data-table compare-table">
                <thead>
                  <tr><th>口径</th><th>数据集代次</th><th>基准区间</th><th>样本量</th><th>结论</th></tr>
                </thead>
                <tbody>
                  <tr>
                    <td>旧结论（历史）</td>
                    <td>{summary.前后对比.旧结论代次}</td>
                    <td>{summary.前后对比.旧基准区间}</td>
                    <td>{summary.前后对比.旧样本量 ?? '—'}</td>
                    <td>{summary.前后对比.旧复核结论}</td>
                  </tr>
                  <tr>
                    <td>新结论（当前）</td>
                    <td>{summary.前后对比.新结论代次}</td>
                    <td>
                      {summary.前后对比.新基准区间}
                      {summary.前后对比.区间是否变化 && <span className="badge">区间已变化</span>}
                    </td>
                    <td>{summary.前后对比.新样本量 ?? '待复核'}</td>
                    <td>{summary.前后对比.新复核结论}</td>
                  </tr>
                </tbody>
              </table>
              <p className="review-note">{summary.前后对比.说明}</p>
            </div>
          )}

          <div className="bucket-grid">
            {BUCKETS.map((bucket) => (
              <section key={bucket} className="bucket" data-bucket={bucket}>
                <h3>
                  <span className="bucket-dot" style={{ background: BUCKET_COLOR[bucket] }} />
                  {bucket}
                  <span className="bucket-count">{reviewsOf(bucket).length}</span>
                </h3>
                {reviewsOf(bucket).map((review) => (
                  <ReviewCard
                    key={`${review.id}-${review.基准区间}`}
                    review={review}
                    canDefer={isLatestGeneration}
                    onDefer={defer}
                    deferring={busy === 'defer'}
                  />
                ))}
                {reviewsOf(bucket).length === 0 && (
                  <p className="empty-state">代次 {activeGeneration} 暂无「{bucket}」结论</p>
                )}
              </section>
            ))}
          </div>

          <section className="history-panel">
            <header className="history-head">
              <h3>历史结论（数据集刷新前的旧口径）</h3>
              <button className="btn ghost" type="button" onClick={() => setShowHistory((value) => !value)}>
                {showHistory ? '收起历史' : '展开历史'}
              </button>
            </header>
            {showHistory && (
              <>
                {summary.历史结论.length === 0 && <p className="empty-state">尚无历史结论</p>}
                {(['显著', '不显著', '样本不足'] as Bucket[]).map((bucket) => (
                  summary.历史分档[bucket].length > 0 && (
                    <div key={bucket} className="history-group">
                      <h4>{bucket} · {summary.历史分档[bucket].length} 条</h4>
                      <div className="history-grid">
                        {summary.历史分档[bucket].map((review) => (
                          <ReviewCard key={`history-${review.id}`} review={review} />
                        ))}
                      </div>
                    </div>
                  )
                ))}
              </>
            )}
          </section>
        </section>
      )}
    </section>
  )
}
