import { useCallback, useEffect, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/export'
const columns = [
  "模板编号",
  "模板名称",
  "数据源绑定",
  "导出格式",
  "字段选择",
  "筛选参数",
  "导出上限",
  "是否启用"
]
const actions = [
  "提交校验",
  "启用配置",
  "停用配置"
]

type Row = {
  id: number
  模板编号: string
  数据源绑定: string
  数据集代次: number
  数据集最近刷新时间: string
  引用实验: string[]
  [key: string]: string | number | null | string[]
}

export default function ExportView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [message, setMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const filterFields = ["模板编号", "数据源绑定"]

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('导出模板列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '数据导出配置列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    setMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: { action } }),
      })
      if (!response.ok) {
        throw new Error('数据导出配置动作未生效，请稍后重试')
      }
      const payload = await response.json()
      setMessage(payload.message ?? '')
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '数据导出配置操作失败')
    }
  }

  return (
    <section className="page" data-module="export">
      <header className="page-head">
        <div>
          <h2>数据导出配置管理</h2>
          <p className="page-desc">
            维护分析结果的导出模板、格式配置与行数控制。导出清单跟随数据集复核代次更新，
            同一数据源绑定显示当前代次与被哪些实验引用。
          </p>
        </div>
        <div className="page-actions">
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出数据导出配置清单
          </button>
        </div>
      </header>

      {errorMessage && <p className="error-text">{errorMessage}</p>}
      {message && <p className="ok-text">{message}</p>}

      <div className="stat-row">
        {[
          { label: '导出模板总数', value: total },
          { label: '待校验导出模板', value: rows.filter((row) => row.status === '待校验').length },
          { label: '已启用导出模板', value: rows.filter((row) => row.status === '已启用').length },
          { label: '绑定数据集代次', value: new Set(rows.map((row) => `${row.数据源绑定}@${row.数据集代次}`)).size },
        ].map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        {filterFields.map((field) => (
          <label key={field} className="filter-item">
            <span>{field}</span>
            <input
              value={filters[field] ?? ''}
              placeholder={`按${field}检索`}
              onChange={(event) => setFilters((prev) => ({ ...prev, [field]: event.target.value }))}
            />
          </label>
        ))}
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>绑定数据集代次</th>
            <th>最近刷新时间</th>
            <th>引用实验</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => <td key={column}>{row[column] ?? '—'}</td>)}
              <td><span className="badge">代次 {row.数据集代次}</span></td>
              <td>{row.数据集最近刷新时间}</td>
              <td>{(row.引用实验 ?? []).length === 0 ? '—' : (row.引用实验 ?? []).join('、')}</td>
              <td className="row-actions">
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 4}>暂无数据导出配置数据，可先登记导出模板</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条数据导出配置记录</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
