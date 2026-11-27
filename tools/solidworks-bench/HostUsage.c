/* macOS per-process counters. Values are cumulative across the process lifetime. */
#include <errno.h>
#include <libproc.h>
#include <mach/mach_time.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/resource.h>

int main(int argc, char **argv)
{
    mach_timebase_info_data_t base;
    if (mach_timebase_info(&base) != KERN_SUCCESS || !base.denom) return 3;
    for (int i = 1; i < argc; ++i)
    {
        char *end;
        long pid = strtol(argv[i], &end, 10);
        if (*end || pid <= 0 || pid > INT32_MAX) return 2;
        struct rusage_info_v6 counters = {0};
        if (proc_pid_rusage((int)pid, RUSAGE_INFO_V6, (rusage_info_t *)&counters))
        {
            fprintf(stderr, "proc_pid_rusage(%ld): errno=%d\n", pid, errno);
            continue;
        }
        uint64_t user_ns = (__uint128_t)counters.ri_user_time * base.numer / base.denom;
        uint64_t system_ns = (__uint128_t)counters.ri_system_time * base.numer / base.denom;
        printf("%ld,%llu,%llu,%llu,%llu\n", pid, (unsigned long long)user_ns,
               (unsigned long long)system_ns, (unsigned long long)counters.ri_phys_footprint,
               (unsigned long long)counters.ri_energy_nj);
    }
    return 0;
}
