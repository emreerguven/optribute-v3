// ════════════════════════════════════════════════════
// Optribute v3 — Google Apps Script
// Reads from: "Depots" sheet + "Deliveries" sheet
// ════════════════════════════════════════════════════

var API_BASE = "https://YOUR-DEPLOY-URL.com"; // ← Deploy URL buraya
var API_URL = API_BASE + "/optimize";

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("Optribute v3")
    .addItem("Open Panel", "showSidebar")
    .addToUi();
}

function showSidebar() {
  var html = HtmlService.createHtmlOutputFromFile("sidebar_v3")
    .setTitle("Optribute v3")
    .setWidth(340);
  SpreadsheetApp.getUi().showSidebar(html);
}

// ────────────────────────────────────────
// Geocoding (works on active sheet)
// ────────────────────────────────────────

function geocodeAddresses() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return 0;

  // Find Address, Lat, Lon columns (B, C, D for Depots; B, C, D for Deliveries)
  var addrCol = 2, latCol = 3, lonCol = 4;
  // For Depots sheet: A=Name, B=Address, C=Lat, D=Lon
  // For Deliveries sheet: A=ID, B=Address, C=Lat, D=Lon
  var data = sheet.getRange(2, addrCol, lastRow - 1, 3).getValues();
  var count = 0;

  for (var i = 0; i < data.length; i++) {
    var addr = data[i][0], lat = data[i][1], lon = data[i][2];
    if (addr !== "" && (lat === "" || lon === "" || lat === "NOT FOUND")) {
      try {
        var resp = Maps.newGeocoder().setRegion("tr").geocode(addr);
        if (resp.status === "OK") {
          var loc = resp.results[0].geometry.location;
          sheet.getRange(i + 2, latCol).setNumberFormat("@").setValue(loc.lat.toString());
          sheet.getRange(i + 2, lonCol).setNumberFormat("@").setValue(loc.lng.toString());
          count++;
        } else {
          sheet.getRange(i + 2, latCol).setValue("NOT FOUND");
          sheet.getRange(i + 2, lonCol).setValue("NOT FOUND");
        }
      } catch (e) {
        sheet.getRange(i + 2, latCol).setValue("ERROR");
      }
    }
  }
  return count;
}

// ────────────────────────────────────────
// Time parsing
// ────────────────────────────────────────

function timeToMinutes(val) {
  if (!val) return null;
  var d = new Date(val);
  if (!isNaN(d.getTime())) return d.getHours() * 60 + d.getMinutes();
  if (typeof val === "string" && val.indexOf(":") > -1) {
    var p = val.split(":");
    return parseInt(p[0]) * 60 + parseInt(p[1]);
  }
  return null;
}

// ────────────────────────────────────────
// Read Depots sheet
// ────────────────────────────────────────
// Format: A=Name, B=Address, C=Lat, D=Lon

function readDepots() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName("Depots");
  if (!sheet) {
    SpreadsheetApp.getUi().alert("'Depots' sheet bulunamadi.\nDepo bilgilerini iceren bir 'Depots' sayfasi olusturun.");
    return null;
  }

  var lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    SpreadsheetApp.getUi().alert("Depots sayfasinda depo bulunamadi.");
    return null;
  }

  var data = sheet.getRange(2, 1, lastRow - 1, 4).getValues(); // A-D
  var depots = [];

  for (var i = 0; i < data.length; i++) {
    var name = data[i][0], lat = data[i][2], lon = data[i][3];
    if (lat === "" || lon === "" || lat === "NOT FOUND") continue;
    depots.push({
      id: -i,  // 0, -1, -2, ...
      lat: parseFloat(lat),
      lon: parseFloat(lon)
    });
  }

  if (depots.length === 0) {
    SpreadsheetApp.getUi().alert("Gecerli depo bulunamadi. Lat/Lon degerlerini kontrol edin.");
    return null;
  }

  return depots;
}

// ────────────────────────────────────────
// Read Deliveries sheet
// ────────────────────────────────────────
// Format: A=ID, B=Address, C=Lat, D=Lon, E=Demand, F=TW Start, G=TW End

function readDeliveries() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName("Deliveries");
  if (!sheet) {
    SpreadsheetApp.getUi().alert("'Deliveries' sheet bulunamadi.\nTeslimat noktalarini iceren bir 'Deliveries' sayfasi olusturun.");
    return null;
  }

  var aCol = sheet.getRange("A:A").getValues();
  var lastRow = 1;
  for (var k = 0; k < aCol.length; k++) { if (aCol[k][0] !== "") lastRow = k + 1; }
  if (lastRow < 2) {
    SpreadsheetApp.getUi().alert("Deliveries sayfasinda teslimat noktasi bulunamadi.");
    return null;
  }

  var data = sheet.getRange(2, 1, lastRow - 1, 7).getValues();
  var jobs = [];

  for (var i = 0; i < data.length; i++) {
    var id = data[i][0], lat = data[i][2], lon = data[i][3];
    if (id === "" || lat === "" || lon === "" || lat === "NOT FOUND") continue;
    jobs.push({
      id: parseInt(id),
      lat: parseFloat(lat),
      lon: parseFloat(lon),
      demand: data[i][4] === "" ? 0 : parseInt(data[i][4]),
      time_start: data[i][5] !== "" ? (timeToMinutes(data[i][5]) || 0) : 0,
      time_end: data[i][6] !== "" ? (timeToMinutes(data[i][6]) || 1440) : 1440,
    });
  }

  if (jobs.length === 0) {
    SpreadsheetApp.getUi().alert("Gecerli teslimat noktasi bulunamadi.");
    return null;
  }

  return { jobs: jobs, lastRow: lastRow };
}

// ────────────────────────────────────────
// Main: Calculate Route
// ────────────────────────────────────────

function calculateRoute(params) {
  var ui = SpreadsheetApp.getUi();

  if (new Date() > new Date("2027-12-31")) {
    ui.alert("Deneme lisansiniz sona erdi.");
    return;
  }

  // Read from separate sheets
  var depots = readDepots();
  if (!depots) return;

  var delData = readDeliveries();
  if (!delData) return;

  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var delSheet = ss.getSheetByName("Deliveries");

  // Clear previous results (H-J and L-Q on Deliveries sheet)
  delSheet.getRange(2, 8, delSheet.getMaxRows() - 1, 3).clearContent();
  delSheet.getRange(1, 12, delSheet.getMaxRows(), 6).clearContent();

  var payload = {
    depots: depots,
    jobs: delData.jobs,
    vehicle_count: params.vehicleCount,
    vehicle_capacity: params.vehicleCapacity || 999999,
    use_capacity: params.useCapacity || false,
    open_route: params.openRoute || false,
    service_time: params.serviceTime || 10,
    route_start_time: params.routeStartTime || 480,
    optimization_goal: params.optGoal || "distance",
    max_ratio: params.maxRatio || 3.0,
    time_limit: params.timeLimit || 30,
  };

  try {
    var response = UrlFetchApp.fetch(API_URL, {
      method: "post",
      contentType: "application/json",
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });

    if (response.getResponseCode() !== 200) {
      ui.alert("Sunucu Hatasi:\n" + response.getContentText());
      return;
    }

    var json = JSON.parse(response.getContentText());
    if (json.status !== "success") {
      ui.alert("Optimizasyon basarisiz: " + JSON.stringify(json));
      return;
    }

    // Write results to Deliveries sheet
    var rawData = delSheet.getRange(2, 1, delData.lastRow - 1, 7).getValues();
    var routeColors = ["\uD83D\uDD34", "\uD83D\uDD35", "\uD83D\uDFE2", "\uD83D\uDFE3", "\uD83D\uDFE0", "\uD83D\uDFE4", "\u26AA"];
    var assignments = rawData.map(function () { return ["", "", ""]; });

    var summaryTable = [["Vehicle", "Km", "Load", "Stops", "Depot", "Goal"]];

    for (var r = 0; r < json.routes.length; r++) {
      var route = json.routes[r];
      if (!route.path || route.path.length === 0) continue;
      var vId = route.vehicle_id;
      var rColor = routeColors[r % routeColors.length];

      for (var p = 0; p < route.path.length; p++) {
        var stop = route.path[p];
        if (stop.original_id > 0) {
          for (var v = 0; v < rawData.length; v++) {
            if (rawData[v][0] == stop.original_id) {
              assignments[v][0] = "Vehicle " + vId;
              assignments[v][1] = stop.order;
              assignments[v][2] = stop.arrival_time;
              break;
            }
          }
        }
      }

      summaryTable.push([
        "V" + vId + " " + rColor,
        route.total_km + " km",
        route.total_load + " kg",
        route.stop_count,
        "D" + (route.depot_id || 0),
        json.solver_info.optimization_goal
      ]);
    }

    delSheet.getRange(2, 8, rawData.length, 3).setValues(assignments);

    if (summaryTable.length > 1) {
      delSheet.getRange(1, 12, summaryTable.length, 6).setValues(summaryTable);
      delSheet.getRange(1, 12, 1, 6)
        .setFontWeight("bold")
        .setBackground("#1565c0")
        .setFontColor("white");
    }

    // Toast
    var si = json.solver_info;
    ss.toast(
      "v3 | " + si.active_vehicles + " vehicles | " +
      json.summary.total_km + " km | " + si.total_time + "s",
      "Optribute v3", 5
    );

  } catch (e) {
    ui.alert("API Baglanti Hatasi: " + e.toString());
  }
}
