#include "udf.h"
#include <stdio.h>

/*
 * Fluent UDF for potato drip-fertigation soil solution percolation.
 *
 * Model coupling used by this project:
 *   - Python/PLC digital twin exports transient boundary data to:
 *       fluent/fluent_soil_boundary.csv
 *   - Fluent porous soil domain solves liquid flow with UDS scalars:
 *       UDS-0: EC-equivalent solute concentration
 *       UDS-1: nitrogen concentration
 *       UDS-2: phosphorus concentration
 *       UDS-3: potassium concentration
 *   - Apply the profile functions below on the drip inlet.
 *
 * Recommended Fluent setup:
 *   - Pressure-based, transient.
 *   - Soil body as porous zone.
 *   - Enable 4 User-Defined Scalars.
 *   - Assign diffusivity with soil_solution_diffusivity.
 *   - Assign scalar sink with ec_root_sink / n_root_sink / p_root_sink / k_root_sink.
 */

#define MAX_PROFILE_ROWS 200000
#define DEFAULT_BOUNDARY_FILE "fluent/fluent_soil_boundary.csv"

static int profile_loaded = 0;
static int profile_n = 0;
static real t_s[MAX_PROFILE_ROWS];
static real irrigation_mm_h[MAX_PROFILE_ROWS];
static real ec_drip[MAX_PROFILE_ROWS];
static real n_drip[MAX_PROFILE_ROWS];
static real p_drip[MAX_PROFILE_ROWS];
static real k_drip[MAX_PROFILE_ROWS];

static real theta_fc = 0.334;
static real theta_wp = 0.090;
static real theta_sat = 0.420;
static real soil_porosity = 0.420;
static real root_depth_m = 0.300;
static real solute_sink_rate = 1.2e-6;
static real nutrient_sink_rate = 8.0e-7;
static real background_ec = 0.20;

static real clamp_real(real value, real lo, real hi)
{
    if (value < lo) return lo;
    if (value > hi) return hi;
    return value;
}

static void read_boundary_profile(void)
{
    FILE *fp;
    char line[1024];
    int n = 0;

    if (profile_loaded) return;

    fp = fopen(DEFAULT_BOUNDARY_FILE, "r");
    if (fp == NULL)
    {
        Message("\n[soil_solution_udf] Boundary file not found: %s\n", DEFAULT_BOUNDARY_FILE);
        Message("[soil_solution_udf] Using fallback zero-irrigation profile.\n");
        profile_n = 1;
        t_s[0] = 0.0;
        irrigation_mm_h[0] = 0.0;
        ec_drip[0] = background_ec;
        n_drip[0] = 0.0;
        p_drip[0] = 0.0;
        k_drip[0] = 0.0;
        profile_loaded = 1;
        return;
    }

    if (fgets(line, sizeof(line), fp) == NULL)
    {
        fclose(fp);
        profile_loaded = 1;
        return;
    }

    while (fgets(line, sizeof(line), fp) != NULL && n < MAX_PROFILE_ROWS)
    {
        double ts, irr, ec, nval, pval, kval;
        int fields = sscanf(line, "%lf,%lf,%lf,%lf,%lf,%lf", &ts, &irr, &ec, &nval, &pval, &kval);
        if (fields >= 3)
        {
            t_s[n] = (real)ts;
            irrigation_mm_h[n] = (real)irr;
            ec_drip[n] = (real)ec;
            n_drip[n] = (fields >= 4) ? (real)nval : 0.0;
            p_drip[n] = (fields >= 5) ? (real)pval : 0.0;
            k_drip[n] = (fields >= 6) ? (real)kval : 0.0;
            n++;
        }
    }
    fclose(fp);

    profile_n = n;
    profile_loaded = 1;
    Message("\n[soil_solution_udf] Loaded %d boundary rows from %s\n", profile_n, DEFAULT_BOUNDARY_FILE);
}

static real interpolate_series(real now, real *series)
{
    int lo = 0;
    int hi = profile_n - 1;
    int mid;
    real ratio;

    if (!profile_loaded) read_boundary_profile();
    if (profile_n <= 0) return 0.0;
    if (now <= t_s[0]) return series[0];
    if (now >= t_s[profile_n - 1]) return series[profile_n - 1];

    while (hi - lo > 1)
    {
        mid = (lo + hi) / 2;
        if (t_s[mid] <= now)
            lo = mid;
        else
            hi = mid;
    }

    ratio = (now - t_s[lo]) / MAX(t_s[hi] - t_s[lo], 1.0e-12);
    return series[lo] * (1.0 - ratio) + series[hi] * ratio;
}

DEFINE_EXECUTE_ON_LOADING(soil_solution_on_load, libname)
{
    Message("\n[soil_solution_udf] Loaded library: %s\n", libname);
    read_boundary_profile();
}

DEFINE_PROFILE(drip_velocity_profile, thread, position)
{
    face_t f;
    real now = CURRENT_TIME;
    real irr = interpolate_series(now, irrigation_mm_h);
    real velocity = MAX(irr, 0.0) / 1000.0 / 3600.0;

    begin_f_loop(f, thread)
    {
        F_PROFILE(f, thread, position) = velocity;
    }
    end_f_loop(f, thread)
}

DEFINE_PROFILE(drip_ec_uds0_profile, thread, position)
{
    face_t f;
    real value = interpolate_series(CURRENT_TIME, ec_drip);

    begin_f_loop(f, thread)
    {
        F_PROFILE(f, thread, position) = value;
    }
    end_f_loop(f, thread)
}

DEFINE_PROFILE(drip_n_uds1_profile, thread, position)
{
    face_t f;
    real value = interpolate_series(CURRENT_TIME, n_drip);

    begin_f_loop(f, thread)
    {
        F_PROFILE(f, thread, position) = value;
    }
    end_f_loop(f, thread)
}

DEFINE_PROFILE(drip_p_uds2_profile, thread, position)
{
    face_t f;
    real value = interpolate_series(CURRENT_TIME, p_drip);

    begin_f_loop(f, thread)
    {
        F_PROFILE(f, thread, position) = value;
    }
    end_f_loop(f, thread)
}

DEFINE_PROFILE(drip_k_uds3_profile, thread, position)
{
    face_t f;
    real value = interpolate_series(CURRENT_TIME, k_drip);

    begin_f_loop(f, thread)
    {
        F_PROFILE(f, thread, position) = value;
    }
    end_f_loop(f, thread)
}

DEFINE_DIFFUSIVITY(soil_solution_diffusivity, c, t, i)
{
    real molecular_d = 1.0e-9;
    real dispersivity = 0.015;
    real velocity_mag;
    real theta_eff = clamp_real(soil_porosity, theta_wp, theta_sat);
    real tortuosity = pow(theta_eff / theta_sat, 1.5);

    velocity_mag = C_U(c, t) * C_U(c, t) + C_V(c, t) * C_V(c, t);
#if RP_3D
    velocity_mag += C_W(c, t) * C_W(c, t);
#endif
    velocity_mag = sqrt(MAX(velocity_mag, 0.0));

    return molecular_d * tortuosity + dispersivity * MAX(velocity_mag, 0.0);
}

static real scalar_first_order_sink(cell_t c, Thread *t, int uds_index, real rate, real background, real *dS)
{
    real concentration = C_UDSI(c, t, uds_index);
    real mobile_fraction = clamp_real((soil_porosity - theta_wp) / MAX(theta_fc - theta_wp, 1.0e-6), 0.0, 1.0);
    real sink = -rate * mobile_fraction * MAX(concentration - background, 0.0);
    dS[0] = -rate * mobile_fraction;
    return sink;
}

DEFINE_SOURCE(ec_root_sink, c, t, dS, eqn)
{
    return scalar_first_order_sink(c, t, 0, solute_sink_rate, background_ec, dS);
}

DEFINE_SOURCE(n_root_sink, c, t, dS, eqn)
{
    return scalar_first_order_sink(c, t, 1, nutrient_sink_rate, 0.0, dS);
}

DEFINE_SOURCE(p_root_sink, c, t, dS, eqn)
{
    return scalar_first_order_sink(c, t, 2, nutrient_sink_rate, 0.0, dS);
}

DEFINE_SOURCE(k_root_sink, c, t, dS, eqn)
{
    return scalar_first_order_sink(c, t, 3, nutrient_sink_rate, 0.0, dS);
}
