# Reflection

AI assistance was used for the portal investigation, implementation and this write-up.

## What assumptions did you make?

Meter IDs identify records, while hierarchy names can disagree or change. The increasing kWh/kVAh values look like cumulative registers, so consumption comes from adjacent differences. The timestamp timezone is assumed to be `Asia/Kolkata`. The API returns the portal's default reading window, which was in June even though the investigation happened in October.

## Which part was most difficult, and how did you get unstuck?

Finding the data behind the pages took the most investigation. The initial HTML had no meter rows, and the detail pages used two different formats. The linked JavaScript exposed the JSON routes and the export signing procedure. That export provided one consistent detail format without needing two page parsers.

## If you had another day, what would you improve?

First, verify whether the portal supports historical date ranges and confirm the register interpretation on more meters. After that, caching would reduce repeated logins and export downloads. Those changes need evidence about the portal's behavior before adding more endpoints or infrastructure.

## What mistake did you make while solving this?

The initial request didn't follow the login redirect and returned an empty body. After authentication, the meter HTML still had no rows. The populated browser view made the cause clear: records arrive after hydration. The inspection needed to follow the page's data requests instead of treating the HTML as the complete response.

## If you were reviewing your own submission, what would you criticise?

Fetching the export for each detail request is inefficient, and logging in for each request adds latency. The service depends on undocumented routes and only supports the default energy window. The consumption calculation also relies on assumptions that need wider verification before anyone uses it for billing. Keeping those limits visible is preferable to hiding them behind a larger implementation.
