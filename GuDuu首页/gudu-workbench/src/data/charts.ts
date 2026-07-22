import type { ChartConfiguration } from 'chart.js'

/** 创建上下渐变填充 */
function gradient(ctx: CanvasRenderingContext2D, c1: string, c2: string) {
  const g = ctx.createLinearGradient(0, 0, 0, 200)
  g.addColorStop(0, c1)
  g.addColorStop(1, c2)
  return g
}

/** chProd：加急订单加工进度（完成量 vs 计划）*/
export function chProdConfig(ctx: CanvasRenderingContext2D): ChartConfiguration {
  return {
    type: 'line',
    data: {
      labels: ['10:00','10:10','10:20','10:30','10:40','10:50','11:00','11:10'],
      datasets: [
        {
          label: '完成量 (斤)',
          data: [0,600,1300,2100,2800,3400,3800,3952],
          borderColor: '#c96442',
          backgroundColor: gradient(ctx, 'rgba(201,100,66,0.18)', 'rgba(201,100,66,0)'),
          fill: true, tension: 0.4, borderWidth: 2, pointRadius: 0
        },
        {
          label: '计划 (斤)',
          data: [0,570,1140,1710,2280,2850,3420,4000],
          borderColor: '#4a7a8c',
          backgroundColor: gradient(ctx, 'rgba(74,122,140,0.15)', 'rgba(74,122,140,0)'),
          fill: true, tension: 0.4, borderWidth: 2, pointRadius: 0
        }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'top', align: 'end', labels: { boxWidth: 10, padding: 12, font: { size: 11 } } } },
      scales: { y: { grid: { color: 'rgba(0,0,0,0.04)' } }, x: { grid: { display: false } } }
    }
  }
}

/** chSave：本月降损节省 */
export function chSaveConfig(): ChartConfiguration {
  return {
    type: 'bar',
    data: {
      labels: ['W1','W2','W3','W4'],
      datasets: [{ label: '降损节省 (万元)', data: [6.8,7.2,7.5,8.1], backgroundColor: '#6b8e4e', borderRadius: 3, barThickness: 30 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { y: { grid: { color: 'rgba(0,0,0,0.04)' } }, x: { grid: { display: false } } }
    }
  }
}

/** chPie：AI 分身协同任务分布 */
export function chPieConfig(): ChartConfiguration<'doughnut'> {
  return {
    type: 'doughnut',
    data: {
      labels: ['货源调度','质检溯源','行情分析','风险预警','其他'],
      datasets: [{ data: [342,267,128,201,148], backgroundColor: ['#c96442','#6b8e4e','#4a7a8c','#b58932','#8a8270'], borderWidth: 0 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'right', labels: { boxWidth: 8, padding: 8, font: { size: 11 } } } },
      cutout: '62%'
    }
  }
}

/** chTrend：大黄鱼批发价 7 日走势（实际 vs AI 预测 vs 历史平均）*/
export function chTrendConfig(ctx: CanvasRenderingContext2D): ChartConfiguration {
  return {
    type: 'line',
    data: {
      labels: ['周一','周二','周三','周四','周五','周六','周日'],
      datasets: [
        { label: '实际 (元/斤)', data: [19.8,19.5,19.2,18.9,18.6,18.4,18.2],
          borderColor: '#c96442',
          backgroundColor: gradient(ctx, 'rgba(201,100,66,0.15)', 'rgba(201,100,66,0)'),
          fill: true, tension: 0.4, borderWidth: 2, pointRadius: 3, pointBackgroundColor: '#c96442' },
        { label: 'AI 预测', data: [19.9,19.6,19.3,19.0,18.7,18.5,18.3],
          borderColor: '#b58932', borderDash: [5,4], fill: false, tension: 0.4, borderWidth: 2, pointRadius: 0 },
        { label: '历史平均', data: [21.0,20.9,20.9,20.8,20.8,20.7,20.7],
          borderColor: 'rgba(0,0,0,0.2)', borderDash: [2,2], fill: false, tension: 0.4, borderWidth: 1.5, pointRadius: 0 }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'top', align: 'end', labels: { boxWidth: 10, padding: 12, font: { size: 11 } } } },
      scales: { y: { grid: { color: 'rgba(0,0,0,0.04)' } }, x: { grid: { display: false } } }
    }
  }
}

/** chP201：冷链车厢温度爬升（实测 vs 上限阈值）*/
export function chP201Config(ctx: CanvasRenderingContext2D): ChartConfiguration {
  return {
    type: 'line',
    data: {
      labels: ['15:13','15:14','15:15','15:16','15:17','15:18','15:19','15:20','15:21'],
      datasets: [
        {
          label: '厢温实测 (℃)',
          data: [3.78,3.80,3.83,3.87,3.92,3.96,4.01,4.04,4.06],
          borderColor: '#c96442',
          backgroundColor: gradient(ctx, 'rgba(201,100,66,0.18)', 'rgba(201,100,66,0)'),
          fill: true, tension: 0.4, borderWidth: 2, pointRadius: 0
        },
        {
          label: '上限阈值 4.0℃',
          data: [4.0,4.0,4.0,4.0,4.0,4.0,4.0,4.0,4.0],
          borderColor: '#b58932', borderDash: [5,4], fill: false, borderWidth: 1.5, pointRadius: 0
        }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'top', align: 'end', labels: { boxWidth: 10, padding: 12, font: { size: 11 } } } },
      scales: { y: { suggestedMin: 3.7, suggestedMax: 4.2, grid: { color: 'rgba(0,0,0,0.04)' } }, x: { grid: { display: false } } }
    }
  }
}

/** chUnit：货源分配（可供 vs 锁定）*/
export function chUnitConfig(): ChartConfiguration {
  return {
    type: 'bar',
    data: {
      labels: ['冷库库存','养殖出塘','捕捞渔获'],
      datasets: [
        { label: '可供 (斤)', data: [2000,1500,1000], backgroundColor: '#d8cfb6', borderRadius: 3 },
        { label: '锁定 (斤)', data: [2000,1500,500], backgroundColor: '#c96442', borderRadius: 3 }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'top', align: 'end', labels: { boxWidth: 10, padding: 12, font: { size: 11 } } } },
      scales: { y: { grid: { color: 'rgba(0,0,0,0.04)' } }, x: { grid: { display: false } } }
    }
  }
}

/** chHelmet：本月异常事件 · 按环节 */
export function chHelmetConfig(): ChartConfiguration {
  return {
    type: 'bar',
    data: {
      labels: ['捕捞','养殖','加工','仓储','冷链物流'],
      datasets: [{
        label: '异常事件',
        data: [4,2,3,1,1],
        backgroundColor: ['#b94a4a','#c96442','#c96442','#b58932','#b58932'],
        borderRadius: 3
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { x: { grid: { color: 'rgba(0,0,0,0.04)' } }, y: { grid: { display: false } } }
    }
  }
}

/** chOil：闽蓝 009 主机油压（实测 vs 基线）*/
export function chOilConfig(ctx: CanvasRenderingContext2D): ChartConfiguration {
  return {
    type: 'line',
    data: {
      labels: ['6/7','6/8','6/9','6/10','6/11','6/12'],
      datasets: [
        {
          label: '油压实测 (bar)',
          data: [2.7,2.6,2.5,2.4,2.2,2.1],
          borderColor: '#c96442',
          backgroundColor: gradient(ctx, 'rgba(201,100,66,0.18)', 'rgba(201,100,66,0)'),
          fill: true, tension: 0.4, borderWidth: 2, pointRadius: 3, pointBackgroundColor: '#c96442'
        },
        {
          label: '基线 2.8 bar',
          data: [2.8,2.8,2.8,2.8,2.8,2.8],
          borderColor: '#b58932', borderDash: [5,4], fill: false, borderWidth: 1.5, pointRadius: 0
        }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'top', align: 'end', labels: { boxWidth: 10, padding: 12, font: { size: 11 } } } },
      scales: { y: { suggestedMin: 1.8, suggestedMax: 3.0, grid: { color: 'rgba(0,0,0,0.04)' } }, x: { grid: { display: false } } }
    }
  }
}

/** chVib：速冻线压缩机振动幅值（实测 vs 报警线）*/
export function chVibConfig(ctx: CanvasRenderingContext2D): ChartConfiguration {
  return {
    type: 'line',
    data: {
      labels: ['6/4','6/5','6/6','6/7','6/8','6/9','6/10','6/11','6/12'],
      datasets: [
        {
          label: '振动幅值 (mm/s)',
          data: [2.6,2.7,2.8,2.8,2.9,3.0,3.1,3.3,3.4],
          borderColor: '#c96442',
          backgroundColor: gradient(ctx, 'rgba(201,100,66,0.18)', 'rgba(201,100,66,0)'),
          fill: true, tension: 0.4, borderWidth: 2, pointRadius: 0
        },
        {
          label: '报警线 4.5 mm/s',
          data: [4.5,4.5,4.5,4.5,4.5,4.5,4.5,4.5,4.5],
          borderColor: '#b94a4a', borderDash: [5,4], fill: false, borderWidth: 1.5, pointRadius: 0
        }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'top', align: 'end', labels: { boxWidth: 10, padding: 12, font: { size: 11 } } } },
      scales: { y: { suggestedMin: 2.0, suggestedMax: 5.0, grid: { color: 'rgba(0,0,0,0.04)' } }, x: { grid: { display: false } } }
    }
  }
}

/** chDO：4 号塘溶氧（下行→增氧机开启后回升）*/
export function chDOConfig(ctx: CanvasRenderingContext2D): ChartConfiguration {
  return {
    type: 'line',
    data: {
      labels: ['12:00','12:30','13:00','13:30','14:00','14:12','14:30','15:00'],
      datasets: [
        {
          label: '溶氧 (mg/L)',
          data: [6.4,6.2,5.9,5.6,5.3,5.2,5.8,6.3],
          borderColor: '#4a7a8c',
          backgroundColor: gradient(ctx, 'rgba(74,122,140,0.18)', 'rgba(74,122,140,0)'),
          fill: true, tension: 0.4, borderWidth: 2, pointRadius: 3, pointBackgroundColor: '#4a7a8c'
        },
        {
          label: '预警线 5.0 mg/L',
          data: [5.0,5.0,5.0,5.0,5.0,5.0,5.0,5.0],
          borderColor: '#b58932', borderDash: [5,4], fill: false, borderWidth: 1.5, pointRadius: 0
        }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'top', align: 'end', labels: { boxWidth: 10, padding: 12, font: { size: 11 } } } },
      scales: { y: { suggestedMin: 4.5, suggestedMax: 7.0, grid: { color: 'rgba(0,0,0,0.04)' } }, x: { grid: { display: false } } }
    }
  }
}

/** chartId -> 配置工厂 */
export const chartFactories: Record<
  string,
  // 不同图表类型有各自的特有 options（如 doughnut 的 cutout），统一用 any 兜底
  (ctx: CanvasRenderingContext2D) => ChartConfiguration<any>
> = {
  chProd:   (ctx) => chProdConfig(ctx),
  chSave:   () => chSaveConfig(),
  chPie:    () => chPieConfig(),
  chTrend:  (ctx) => chTrendConfig(ctx),
  chP201:   (ctx) => chP201Config(ctx),
  chUnit:   () => chUnitConfig(),
  chHelmet: () => chHelmetConfig(),
  chOil:    (ctx) => chOilConfig(ctx),
  chVib:    (ctx) => chVibConfig(ctx),
  chDO:     (ctx) => chDOConfig(ctx)
}
