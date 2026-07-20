import { readFile, writeFile } from "node:fs/promises";

const LAND_SOURCE = new URL("../assets/land-110m.json", import.meta.url);
const OUTPUT = new URL("../assets/world-hex-land-cells.json", import.meta.url);

function naturalEarth1Raw(longitude, latitude) {
  const lambda = (longitude * Math.PI) / 180;
  const phi = (latitude * Math.PI) / 180;
  const phi2 = phi * phi;
  const phi4 = phi2 * phi2;
  return [
    lambda * (0.8707 - 0.131979 * phi2 + phi4 * (-0.013791 + phi4 * (0.003971 * phi2 - 0.001529 * phi4))),
    phi * (1.007226 + phi2 * (0.015085 + phi4 * (-0.044475 + 0.028874 * phi2 - 0.005916 * phi4))),
  ];
}

function invertNaturalEarth1Raw(x, y) {
  let phi = y;
  let iteration = 25;
  let delta = Infinity;

  while (Math.abs(delta) > 1e-12 && iteration > 0) {
    const phi2 = phi * phi;
    const phi4 = phi2 * phi2;
    const projectedY =
      phi * (1.007226 + phi2 * (0.015085 + phi4 * (-0.044475 + 0.028874 * phi2 - 0.005916 * phi4)));
    const derivative =
      1.007226 + phi2 * (0.045255 + phi4 * (-0.311115 + phi2 * (0.61284 - 0.14358 * phi2)));
    delta = (projectedY - y) / derivative;
    phi -= delta;
    iteration -= 1;
  }

  const phi2 = phi * phi;
  const phi4 = phi2 * phi2;
  const longitudeFactor =
    0.8707 - 0.131979 * phi2 + phi4 * (-0.013791 + phi4 * (0.003971 * phi2 - 0.001529 * phi4));
  return [x / longitudeFactor, phi];
}

function decodeLandPolygons(topology) {
  const landObject = topology?.objects?.land;
  const sourceArcs = topology?.arcs;
  const transform = topology?.transform;
  if (!landObject || !Array.isArray(sourceArcs) || !transform?.scale || !transform?.translate) {
    throw new Error("Invalid Natural Earth topology");
  }

  const [scaleX, scaleY] = transform.scale;
  const [translateX, translateY] = transform.translate;
  const decodedArcCache = new Map();

  const decodeArc = (signedIndex) => {
    const arcIndex = signedIndex < 0 ? ~signedIndex : signedIndex;
    if (!decodedArcCache.has(arcIndex)) {
      let x = 0;
      let y = 0;
      const points = sourceArcs[arcIndex].map(([deltaX, deltaY]) => {
        x += deltaX;
        y += deltaY;
        return [x * scaleX + translateX, y * scaleY + translateY];
      });
      decodedArcCache.set(arcIndex, points);
    }
    const points = decodedArcCache.get(arcIndex);
    return signedIndex < 0 ? [...points].reverse() : points;
  };

  const stitchRing = (arcIndexes) => {
    const ring = [];
    arcIndexes.forEach((arcIndex, index) => {
      const points = decodeArc(arcIndex);
      ring.push(...(index === 0 ? points : points.slice(1)));
    });
    return ring;
  };

  const geometries = landObject.type === "GeometryCollection" ? landObject.geometries : [landObject];
  const polygons = [];
  geometries.forEach((geometry) => {
    const polygonArcs =
      geometry.type === "Polygon" ? [geometry.arcs] : geometry.type === "MultiPolygon" ? geometry.arcs : [];
    polygonArcs.forEach((rings) => {
      const polygon = rings.map(stitchRing).filter((ring) => ring.length >= 3);
      const maximumLatitude = polygon.reduce(
        (maximum, ring) => Math.max(maximum, ...ring.map((point) => point[1])),
        -Infinity,
      );
      if (polygon.length && maximumLatitude > -60) polygons.push(polygon);
    });
  });
  return polygons;
}

function createProjection(polygons) {
  let minimumX = Infinity;
  let maximumX = -Infinity;
  let minimumY = Infinity;
  let maximumY = -Infinity;

  polygons.forEach((polygon) => {
    polygon.forEach((ring) => {
      ring.forEach(([longitude, latitude]) => {
        const [x, y] = naturalEarth1Raw(longitude, latitude);
        minimumX = Math.min(minimumX, x);
        maximumX = Math.max(maximumX, x);
        minimumY = Math.min(minimumY, y);
        maximumY = Math.max(maximumY, y);
      });
    });
  });

  const extent = { x: 38, y: 18, width: 924, height: 420 };
  const rawWidth = maximumX - minimumX;
  const rawHeight = maximumY - minimumY;
  const scale = Math.min(extent.width / rawWidth, extent.height / rawHeight);
  const translateX = extent.x + (extent.width - rawWidth * scale) / 2 - minimumX * scale;
  const translateY = extent.y + (extent.height - rawHeight * scale) / 2 + maximumY * scale;

  return {
    invert([x, y]) {
      const rawX = (x - translateX) / scale;
      const rawY = (translateY - y) / scale;
      const [longitude, latitude] = invertNaturalEarth1Raw(rawX, rawY);
      return [(longitude * 180) / Math.PI, (latitude * 180) / Math.PI];
    },
  };
}

function prepareLandTester(polygons, projection) {
  const preparedPolygons = polygons.map((polygon) => {
    const rings = polygon.map((ring) => {
      const points = [];
      let previousLongitude = ring[0][0];
      ring.forEach(([longitude, latitude], index) => {
        let unwrappedLongitude = longitude;
        if (index > 0) {
          while (unwrappedLongitude - previousLongitude > 180) unwrappedLongitude -= 360;
          while (unwrappedLongitude - previousLongitude < -180) unwrappedLongitude += 360;
        }
        points.push([unwrappedLongitude, latitude]);
        previousLongitude = unwrappedLongitude;
      });

      const longitudes = points.map((point) => point[0]);
      const latitudes = points.map((point) => point[1]);
      const minimumLongitude = Math.min(...longitudes);
      const maximumLongitude = Math.max(...longitudes);
      return {
        points,
        minimumLongitude,
        maximumLongitude,
        minimumLatitude: Math.min(...latitudes),
        maximumLatitude: Math.max(...latitudes),
        centerLongitude: (minimumLongitude + maximumLongitude) / 2,
      };
    });

    return {
      rings,
      minimumLatitude: Math.min(...rings.map((ring) => ring.minimumLatitude)),
      maximumLatitude: Math.max(...rings.map((ring) => ring.maximumLatitude)),
    };
  });

  const pointInRing = (longitude, latitude, ring) => {
    if (latitude < ring.minimumLatitude || latitude > ring.maximumLatitude) return false;
    const shiftedLongitude = longitude + 360 * Math.round((ring.centerLongitude - longitude) / 360);
    if (shiftedLongitude < ring.minimumLongitude || shiftedLongitude > ring.maximumLongitude) return false;

    let inside = false;
    for (let index = 0, previous = ring.points.length - 1; index < ring.points.length; previous = index, index += 1) {
      const [x, y] = ring.points[index];
      const [previousX, previousY] = ring.points[previous];
      if ((y > latitude) === (previousY > latitude)) continue;
      const edgeLongitude = ((previousX - x) * (latitude - y)) / (previousY - y) + x;
      if (shiftedLongitude < edgeLongitude) inside = !inside;
    }
    return inside;
  };

  return (x, y) => {
    const [longitude, latitude] = projection.invert([x, y]);
    for (const polygon of preparedPolygons) {
      if (latitude < polygon.minimumLatitude || latitude > polygon.maximumLatitude) continue;
      let inside = false;
      for (const ring of polygon.rings) {
        if (pointInRing(longitude, latitude, ring)) inside = !inside;
      }
      if (inside) return true;
    }
    return false;
  };
}

const topology = JSON.parse(await readFile(LAND_SOURCE, "utf8"));
const polygons = decodeLandPolygons(topology);
const projection = createProjection(polygons);
const isLand = prepareLandTester(polygons, projection);
const grid = {
  xStart: 48,
  xEnd: 952,
  xStep: 9.15,
  yStart: 24,
  yEnd: 446,
  yStep: 10.45,
};
const cells = [];
let column = 0;

for (let x = grid.xStart; x <= grid.xEnd; x += grid.xStep) {
  const offsetY = (column % 2) * (grid.yStep / 2);
  for (let y = grid.yStart + offsetY; y <= grid.yEnd; y += grid.yStep) {
    if (isLand(x, y)) cells.push([Number(x.toFixed(2)), Number(y.toFixed(2))]);
  }
  column += 1;
}

const output = {
  version: 1,
  source: "Natural Earth 110m land",
  projection: "Natural Earth 1",
  antimeridian: "geographic-point-in-polygon",
  viewBox: [0, 0, 1000, 480],
  grid,
  cells,
};

await writeFile(OUTPUT, `${JSON.stringify(output)}\n`, "utf8");
console.log(`Generated ${cells.length} world-map land cells.`);
