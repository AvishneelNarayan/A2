const charts = [
  ["#network_map", "js/vega/01_network_map.json?v=20260522b"],
  ["#stop_point_map", "js/vega/02_stop_point_map.json?v=20260522b"],
  ["#mode_counts_bar", "js/vega/03_mode_counts_bar.json?v=20260522b"],
  ["#stop_density_choropleth", "js/vega/04_stop_density_choropleth.json?v=20260522b"],
  ["#mode_small_multiples", "js/vega/05_mode_small_multiples.json?v=20260522b"],
  ["#mode_mix_stacked_bar", "js/vega/06_mode_mix_stacked_bar.json?v=20260522b"],
  ["#mode_coverage_dotplot", "js/vega/07_mode_coverage_dotplot.json?v=20260522b"],
  ["#population_access_choropleth", "js/vega/08_population_access_choropleth.json?v=20260522b"],
  ["#population_vs_stops_scatter", "js/vega/09_population_vs_stops_scatter.json?v=20260522b"],
  ["#ranked_access_bar", "js/vega/10_ranked_access_bar.json?v=20260522b"],
  ["#access_score_choropleth", "js/vega/11_access_score_choropleth.json?v=20260522b"],
  ["#hourly_service_heatmap", "js/vega/12_hourly_service_heatmap.json?v=20260522b"]
];

const embedOptions = {
  actions: false,
  renderer: "svg"
};

charts.forEach(([target, spec]) => {
  vegaEmbed(target, spec, embedOptions).catch((error) => {
    const el = document.querySelector(target);
    if (el) {
      el.innerHTML = `<p class="error">This visualisation could not load: ${error.message}</p>`;
    }
    console.error(error);
  });
});
