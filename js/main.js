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
  let zoom = 1;
  let baseHeight = 0;
  const controls = document.createElement("div");
  controls.className = "map-zoom-controls";

  const buttons = [
    ["-", "Zoom out", () => setZoom(Math.max(0.8, zoom - 0.2))],
    ["1x", "Reset zoom", () => setZoom(1)],
    ["+", "Zoom in", () => setZoom(Math.min(2, zoom + 0.2))]
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

  function setZoom(nextZoom) {
    zoom = Number(nextZoom.toFixed(1));
    const embed = container.querySelector(".vega-embed");
    if (!embed) return;
    if (!baseHeight) {
      baseHeight = embed.getBoundingClientRect().height;
    }
    embed.style.transform = `scale(${zoom})`;
    embed.style.marginBottom = zoom > 1 ? `${baseHeight * (zoom - 1)}px` : "0";
    container.classList.toggle("is-zoomed", zoom > 1);
  }

  setZoom(zoom);
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
