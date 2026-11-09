(function () {
  const data = JSON.parse(document.getElementById('dashboard-data').textContent);
  const ROUTE_COLORS = {Cidade: '#286a9b', Misto: '#7651a8', Estrada: '#e48b31'};
  const BAND_COLORS = {'Etanol dominante': '#35a87e', 'Mistura': '#e3a632', 'Gasolina dominante': '#286a9b'};
  const GRID = '#edf1ee';
  const nf = (value, places) => value == null ? '—' : value.toLocaleString('pt-BR', {minimumFractionDigits: places, maximumFractionDigits: places});
  const state = {trend: true, timeline: 'efficiency', matrixMetric: 'cost_per_km', matrixGroup: 'band', ratio: 'ratio'};
  const charts = {};

  Chart.defaults.font.family = 'Inter, ui-sans-serif, system-ui, sans-serif';
  Chart.defaults.color = '#4d5d54';

  function mount(key, canvasId, config) {
    if (charts[key]) charts[key].destroy();
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    charts[key] = new Chart(canvas, config);
  }

  function openOnClick(getUrl) {
    return (event, elements, chart) => {
      const hit = elements[0];
      if (!hit) return;
      const url = getUrl(chart, hit);
      if (url) window.location.href = url;
    };
  }

  function hoverCursor(event, elements) {
    event.native.target.style.cursor = elements.length ? 'pointer' : 'default';
  }

  // ---- Dispersão (eficiência / custo × gasolina C consumida) com linhas de tendência ----
  function scatterConfig(points, fits, metricKey, axisTitle, places) {
    const datasets = [];
    Object.keys(ROUTE_COLORS).forEach(route => {
      datasets.push({
        kind: 'points', route, label: route,
        data: points.filter(p => p.route === route),
        backgroundColor: ROUTE_COLORS[route] + 'cc', borderColor: ROUTE_COLORS[route],
        pointRadius: 5, pointHoverRadius: 8,
      });
    });
    Object.keys(ROUTE_COLORS).forEach(route => {
      const fit = fits[route] && fits[route][metricKey];
      if (!fit) return;
      datasets.push({
        kind: 'fit', route, type: 'line', label: `Tendência ${route} (R² ${nf(fit.r2, 2)}, ${fit.n} ciclos)`,
        data: [{x: fit.x0, y: fit.y0}, {x: fit.x1, y: fit.y1}],
        borderColor: ROUTE_COLORS[route], borderDash: [6, 4], borderWidth: 2, pointRadius: 0, fill: false,
        hidden: !state.trend,
      });
    });
    return {
      type: 'scatter',
      data: {datasets},
      options: {
        responsive: true, maintainAspectRatio: false,
        onClick: openOnClick((chart, hit) => {
          const dataset = chart.data.datasets[hit.datasetIndex];
          return dataset.kind === 'points' ? dataset.data[hit.index].url : null;
        }),
        onHover: hoverCursor,
        scales: {
          x: {title: {display: true, text: 'Gasolina C consumida no ciclo (%)'}, min: 0, max: 100, grid: {color: GRID}},
          y: {title: {display: true, text: axisTitle}, grid: {color: GRID}},
        },
        plugins: {
          legend: {position: 'bottom', labels: {filter: (item, chart) => chart.datasets[item.datasetIndex].kind === 'points'}, onClick: toggleRoute},
          tooltip: {
            filter: item => item.dataset.kind === 'points',
            callbacks: {
              title: items => `${items[0].raw.date} · ${items[0].dataset.label}`,
              label: item => [
                `${axisTitle}: ${nf(item.raw.y, places)}`,
                `Gasolina C consumida: ${nf(item.raw.x, 0)}%`,
                `${nf(item.raw.km, 0)} km no ciclo`,
              ],
              footer: () => 'Clique para abrir o registro',
            },
          },
        },
      },
    };
  }

  function toggleRoute(event, item, legend) {
    const chart = legend.chart;
    const route = chart.data.datasets[item.datasetIndex].route;
    const show = !chart.isDatasetVisible(item.datasetIndex);
    chart.data.datasets.forEach((dataset, index) => {
      if (dataset.route !== route) return;
      chart.setDatasetVisibility(index, dataset.kind === 'fit' ? show && state.trend : show);
    });
    chart.update();
  }

  function applyTrendVisibility() {
    ['efficiency', 'cost'].forEach(key => {
      const chart = charts[key];
      if (!chart) return;
      chart.data.datasets.forEach((dataset, index) => {
        if (dataset.kind !== 'fit') return;
        const pointsIndex = chart.data.datasets.findIndex(d => d.kind === 'points' && d.route === dataset.route);
        chart.setDatasetVisibility(index, state.trend && chart.isDatasetVisible(pointsIndex));
      });
      chart.update();
    });
  }

  function drawScatters() {
    mount('efficiency', 'efficiencyChart', scatterConfig(data.efficiency, data.fits, 'efficiency', 'km/L', 2));
    mount('cost', 'costChart', scatterConfig(data.cost, data.fits, 'cost', 'R$/km', 3));
  }

  // ---- Evolução por ciclo ----
  function drawTimeline() {
    const t = data.timeline;
    const isEfficiency = state.timeline === 'efficiency';
    const values = isEfficiency ? t.efficiency : t.cost;
    const average = isEfficiency ? t.efficiency_avg : t.cost_avg;
    const places = isEfficiency ? 2 : 3;
    const unit = isEfficiency ? 'km/L' : 'R$/km';
    mount('timeline', 'timelineChart', {
      type: 'line',
      data: {
        labels: t.labels,
        datasets: [
          {label: `${unit} do ciclo`, data: values, borderColor: '#9fb0a6', borderWidth: 1.5, tension: 0.2,
            pointBackgroundColor: t.routes.map(r => ROUTE_COLORS[r]), pointBorderColor: t.routes.map(r => ROUTE_COLORS[r]),
            pointRadius: 5, pointHoverRadius: 8},
          {label: 'Média móvel (3 ciclos)', data: average, borderColor: '#176b4c', borderWidth: 3, tension: 0.35, pointRadius: 0},
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        onClick: openOnClick((chart, hit) => hit.datasetIndex === 0 ? t.urls[hit.index] : null),
        onHover: hoverCursor,
        scales: {x: {grid: {color: GRID}}, y: {title: {display: true, text: unit}, grid: {color: GRID}}},
        plugins: {
          legend: {position: 'bottom'},
          tooltip: {callbacks: {
            title: items => `${items[0].label} · ${t.routes[items[0].dataIndex]}`,
            label: item => `${item.dataset.label}: ${nf(item.parsed.y, places)}`,
          }},
        },
      },
    });
  }

  // ---- Comparativo faixa de mistura × trajeto ----
  function drawMatrix() {
    const metric = state.matrixMetric;
    const byBand = state.matrixGroup === 'band';
    const routes = Object.keys(ROUTE_COLORS);
    const bands = Object.keys(BAND_COLORS);
    const cell = (route, band) => data.matrix.find(item => item.route === route && item.band === band);
    const labels = byBand ? bands : routes;
    const series = byBand ? routes : bands;
    const colors = byBand ? ROUTE_COLORS : BAND_COLORS;
    const datasets = series.map(name => ({
      label: name,
      backgroundColor: colors[name], borderRadius: 6,
      data: labels.map(label => {
        const item = byBand ? cell(name, label) : cell(label, name);
        return item && item.count ? item[metric] : null;
      }),
      cells: labels.map(label => (byBand ? cell(name, label) : cell(label, name))),
    }));
    const unit = metric === 'cost_per_km' ? 'R$/km' : 'km/L';
    const places = metric === 'cost_per_km' ? 3 : 2;
    mount('matrix', 'matrixChart', {
      type: 'bar',
      data: {labels, datasets},
      options: {
        responsive: true, maintainAspectRatio: false,
        scales: {x: {grid: {display: false}}, y: {title: {display: true, text: unit}, grid: {color: GRID}, beginAtZero: true}},
        plugins: {
          legend: {position: 'bottom'},
          tooltip: {callbacks: {
            label: item => {
              const info = item.dataset.cells[item.dataIndex];
              return `${item.dataset.label}: ${nf(item.parsed.y, places)} ${unit} (${info.count} ${info.count === 1 ? 'ciclo' : 'ciclos'}, ${nf(info.distance, 0)} km)`;
            },
          }},
        },
      },
    });
  }

  // ---- Gasto mensal e custo/km ----
  function drawMonthly() {
    const m = data.monthly;
    mount('monthly', 'monthlyChart', {
      data: {
        labels: m.labels,
        datasets: [
          {type: 'bar', label: 'Gasto no mês (R$)', data: m.spend, backgroundColor: '#35a87e99', borderRadius: 6, yAxisID: 'y'},
          {type: 'line', label: 'Custo/km ponderado (R$)', data: m.cost_per_km, borderColor: '#b33a3a', backgroundColor: '#b33a3a',
            tension: 0.25, pointRadius: 4, yAxisID: 'y1'},
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        scales: {
          x: {grid: {display: false}},
          y: {title: {display: true, text: 'Gasto (R$)'}, grid: {color: GRID}, beginAtZero: true},
          y1: {position: 'right', title: {display: true, text: 'R$/km'}, grid: {display: false}},
        },
        plugins: {
          legend: {position: 'bottom'},
          tooltip: {callbacks: {afterBody: items => `${nf(m.distance[items[0].dataIndex], 0)} km rodados em ciclos fechados`}},
        },
      },
    });
  }

  // ---- Relação de preços / preços ----
  function drawRatio() {
    const r = data.ratio;
    if (state.ratio === 'prices') {
      mount('ratio', 'ratioChart', {
        type: 'line',
        data: {labels: r.labels, datasets: [
          {label: 'Gasolina (R$/L)', data: r.gasoline, borderColor: '#286a9b', backgroundColor: '#286a9b', tension: 0.2, pointRadius: 3},
          {label: 'Etanol (R$/L)', data: r.ethanol, borderColor: '#35a87e', backgroundColor: '#35a87e', tension: 0.2, pointRadius: 3},
        ]},
        options: {responsive: true, maintainAspectRatio: false, scales: {x: {grid: {color: GRID}}, y: {title: {display: true, text: 'R$/L'}, grid: {color: GRID}}}, plugins: {legend: {position: 'bottom'}}},
      });
      return;
    }
    const upper = r.limits.map(v => v + r.neutral);
    const lower = r.limits.map(v => v - r.neutral);
    const pointColors = r.values.map((v, i) => v < lower[i] ? '#35a87e' : v > upper[i] ? '#286a9b' : '#e48b31');
    mount('ratio', 'ratioChart', {
      type: 'line',
      data: {labels: r.labels, datasets: [
        {label: 'Relação etanol/gasolina (%)', data: r.values, borderColor: '#176b4c', tension: 0.2, pointRadius: 5,
          pointBackgroundColor: pointColors, pointBorderColor: pointColors, order: 0},
        {label: 'Limite aplicável', data: r.limits, borderColor: '#4d5d54', borderDash: [6, 5], pointRadius: 0, order: 1},
        {label: 'Faixa neutra', data: upper, borderColor: 'transparent', backgroundColor: '#e48b3128', pointRadius: 0, fill: '+1', order: 2},
        {label: 'Faixa neutra (inferior)', data: lower, borderColor: 'transparent', pointRadius: 0, order: 2},
      ]},
      options: {
        responsive: true, maintainAspectRatio: false,
        scales: {x: {grid: {color: GRID}}, y: {title: {display: true, text: 'Percentual (%)'}, grid: {color: GRID}}},
        plugins: {
          legend: {position: 'bottom', labels: {filter: item => item.text !== 'Faixa neutra (inferior)'}},
          tooltip: {filter: item => !item.dataset.label.startsWith('Faixa neutra'), callbacks: {label: item => `${item.dataset.label}: ${nf(item.parsed.y, 2)}%`}},
        },
      },
    });
  }

  // ---- Composição do tanque ----
  function drawComposition() {
    const c = data.composition;
    mount('composition', 'compositionChart', {
      type: 'bar',
      data: {labels: c.labels, datasets: [
        {label: 'Gasolina A', data: c.gasoline_a, backgroundColor: '#286a9b'},
        {label: 'Etanol anidro (na gasolina C)', data: c.anhydrous, backgroundColor: '#e3a632'},
        {label: 'Etanol hidratado', data: c.hydrated, backgroundColor: '#35a87e'},
      ]},
      options: {
        responsive: true, maintainAspectRatio: false,
        scales: {x: {stacked: true, grid: {display: false}}, y: {stacked: true, max: 100, title: {display: true, text: 'Composição do tanque (%)'}, grid: {color: GRID}}},
        plugins: {legend: {position: 'bottom'}, tooltip: {callbacks: {label: item => `${item.dataset.label}: ${nf(item.parsed.y, 1)}%`}}},
      },
    });
  }

  // ---- Controles ----
  function bindSegmented(group, key, redraw) {
    const buttons = document.querySelectorAll(`[data-segment="${group}"] button`);
    buttons.forEach(button => button.addEventListener('click', () => {
      state[key] = button.dataset.value;
      buttons.forEach(other => other.setAttribute('aria-pressed', String(other === button)));
      redraw();
    }));
  }

  bindSegmented('timeline', 'timeline', drawTimeline);
  bindSegmented('matrix-metric', 'matrixMetric', drawMatrix);
  bindSegmented('matrix-group', 'matrixGroup', drawMatrix);
  bindSegmented('ratio', 'ratio', drawRatio);

  const trendToggle = document.getElementById('trendToggle');
  if (trendToggle) trendToggle.addEventListener('change', () => { state.trend = trendToggle.checked; applyTrendVisibility(); });

  drawScatters();
  drawTimeline();
  drawMatrix();
  drawMonthly();
  drawRatio();
  drawComposition();
})();
