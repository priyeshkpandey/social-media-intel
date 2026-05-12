// Selective ECharts registration. Importing from `echarts/core` + listing only
// the chart types and components we use keeps the bundle ~150KB gzipped instead
// of ~250KB for `import * as echarts from "echarts"`.

import * as echarts from "echarts/core";
import { HeatmapChart, LineChart, TreemapChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  TreemapChart,
  LineChart,
  HeatmapChart,
  TitleComponent,
  TooltipComponent,
  GridComponent,
  VisualMapComponent,
  LegendComponent,
  DataZoomComponent,
  CanvasRenderer,
]);

export { echarts };

export function bindResize(chart: ReturnType<typeof echarts.init>, container: Element): void {
  const ro = new ResizeObserver(() => chart.resize());
  ro.observe(container);
}
