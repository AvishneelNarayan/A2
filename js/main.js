const charts = [
  ["#network_map", "js/vega/01_network_map.json?v=20260522c", true],
  ["#stop_point_map", "js/vega/02_stop_point_map.json?v=20260522c", true],
  ["#mode_counts_bar", "js/vega/03_mode_counts_bar.json?v=20260522c", false],
  ["#stop_density_choropleth", "js/vega/04_stop_density_choropleth.json?v=20260529b", true],
  ["#mode_small_multiples", "js/vega/05_mode_small_multiples.json?v=20260529b", true],
  ["#mode_mix_stacked_bar", "js/vega/06_mode_mix_stacked_bar.json?v=20260522c", false],
  ["#mode_coverage_dotplot", "js/vega/07_mode_coverage_dotplot.json?v=20260522c", false],
  ["#population_access_choropleth", "js/vega/08_population_access_choropleth.json?v=20260529b", true],
  ["#population_vs_stops_scatter", "js/vega/09_population_vs_stops_scatter.json?v=20260522c", false],
  ["#ranked_access_bar", "js/vega/10_ranked_access_bar.json?v=20260522c", false],
  ["#access_score_choropleth", "js/vega/11_access_score_choropleth.json?v=20260522c", true],
  ["#hourly_service_heatmap", "js/vega/12_hourly_service_heatmap.json?v=20260522c", false]
];

const embedOptions = {
  actions: false,
  renderer: "svg"
};

function addMapZoom(container) {
  container.classList.add("is-zoomable");
  const embed = container.querySelector(".vega-embed");
  if (!embed) return;

  const viewport = document.createElement("div");
  viewport.className = "map-viewport";
  embed.parentNode.insertBefore(viewport, embed);
  viewport.appendChild(embed);

  const state = {
    scale: 1,
    x: 0,
    y: 0,
    isDragging: false,
    startX: 0,
    startY: 0,
    originX: 0,
    originY: 0
  };

  const controls = document.createElement("div");
  controls.className = "map-zoom-controls";

  const buttons = [
    ["-", "Zoom out", () => zoomAtCenter(0.82)],
    ["1x", "Reset zoom", resetZoom],
    ["+", "Zoom in", () => zoomAtCenter(1.22)]
  ];

  buttons.forEach(([label, title, handler]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.title = title;
    button.setAttribute("aria-label", title);
    button.addEventListener("click", handler);
    controls.appendChild(button);
  });

  container.prepend(controls);

  function applyZoom() {
    embed.style.transform = `translate(${state.x}px, ${state.y}px) scale(${state.scale})`;
    container.classList.toggle("is-zoomed", state.scale > 1);
  }

  function zoomAround(clientX, clientY, factor) {
    const rect = viewport.getBoundingClientRect();
    const nextScale = Math.min(4, Math.max(1, state.scale * factor));
    const scaleRatio = nextScale / state.scale;
    const pointerX = clientX - rect.left;
    const pointerY = clientY - rect.top;

    state.x = pointerX - (pointerX - state.x) * scaleRatio;
    state.y = pointerY - (pointerY - state.y) * scaleRatio;
    state.scale = nextScale;

    if (state.scale === 1) {
      state.x = 0;
      state.y = 0;
    }

    applyZoom();
  }

  function zoomAtCenter(factor) {
    const rect = viewport.getBoundingClientRect();
    zoomAround(rect.left + rect.width / 2, rect.top + rect.height / 2, factor);
  }

  function resetZoom() {
    state.scale = 1;
    state.x = 0;
    state.y = 0;
    applyZoom();
  }

  viewport.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoomAround(event.clientX, event.clientY, event.deltaY < 0 ? 1.14 : 0.88);
  }, { passive: false });

  viewport.addEventListener("pointerdown", (event) => {
    if (state.scale <= 1) return;
    state.isDragging = true;
    state.startX = event.clientX;
    state.startY = event.clientY;
    state.originX = state.x;
    state.originY = state.y;
    viewport.classList.add("is-panning");
    viewport.setPointerCapture(event.pointerId);
  });

  viewport.addEventListener("pointermove", (event) => {
    if (!state.isDragging) return;
    state.x = state.originX + event.clientX - state.startX;
    state.y = state.originY + event.clientY - state.startY;
    applyZoom();
  });

  viewport.addEventListener("pointerup", (event) => {
    state.isDragging = false;
    viewport.classList.remove("is-panning");
    viewport.releasePointerCapture(event.pointerId);
  });

  viewport.addEventListener("pointercancel", () => {
    state.isDragging = false;
    viewport.classList.remove("is-panning");
  });

  applyZoom();
}

charts.forEach(([target, spec, zoomable]) => {
  vegaEmbed(target, spec, embedOptions).then(() => {
    const el = document.querySelector(target);
    if (el && zoomable) {
      addMapZoom(el);
    }
  }).catch((error) => {
    const el = document.querySelector(target);
    if (el) {
      el.innerHTML = `<p class="error">This visualisation could not load: ${error.message}</p>`;
    }
    console.error(error);
  });
});
