/* LD_PRELOAD shim for a kernel without IPv6 (this cloud container): IPv6 sockets become IPv4
 * ones, and IPv6 addresses passed to bind/connect become their IPv4 equivalents
 * (:: -> 0.0.0.0, ::1 -> 127.0.0.1, ::ffff:a.b.c.d -> a.b.c.d). Used only to run the arena
 * client's sc2_controller here, whose port picker binds every port on both families. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <netinet/in.h>
#include <string.h>
#include <sys/socket.h>

static int (*real_socket)(int, int, int);
static int (*real_bind)(int, const struct sockaddr *, socklen_t);
static int (*real_connect)(int, const struct sockaddr *, socklen_t);
static int (*real_setsockopt)(int, int, int, const void *, socklen_t);

static void to_v4(const struct sockaddr *addr, struct sockaddr_in *out) {
    const struct sockaddr_in6 *a6 = (const struct sockaddr_in6 *)addr;
    memset(out, 0, sizeof(*out));
    out->sin_family = AF_INET;
    out->sin_port = a6->sin6_port;
    if (IN6_IS_ADDR_V4MAPPED(&a6->sin6_addr))
        memcpy(&out->sin_addr, &a6->sin6_addr.s6_addr[12], 4);
    else if (IN6_IS_ADDR_LOOPBACK(&a6->sin6_addr))
        out->sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    else
        out->sin_addr.s_addr = htonl(INADDR_ANY);
}

int socket(int domain, int type, int protocol) {
    if (!real_socket) real_socket = dlsym(RTLD_NEXT, "socket");
    return real_socket(domain == AF_INET6 ? AF_INET : domain, type, protocol);
}

int bind(int fd, const struct sockaddr *addr, socklen_t len) {
    if (!real_bind) real_bind = dlsym(RTLD_NEXT, "bind");
    if (addr && addr->sa_family == AF_INET6) {
        struct sockaddr_in v4;
        to_v4(addr, &v4);
        return real_bind(fd, (const struct sockaddr *)&v4, sizeof(v4));
    }
    return real_bind(fd, addr, len);
}

int connect(int fd, const struct sockaddr *addr, socklen_t len) {
    if (!real_connect) real_connect = dlsym(RTLD_NEXT, "connect");
    if (addr && addr->sa_family == AF_INET6) {
        struct sockaddr_in v4;
        to_v4(addr, &v4);
        return real_connect(fd, (const struct sockaddr *)&v4, sizeof(v4));
    }
    return real_connect(fd, addr, len);
}

int setsockopt(int fd, int level, int name, const void *value, socklen_t len) {
    if (!real_setsockopt) real_setsockopt = dlsym(RTLD_NEXT, "setsockopt");
    if (level == IPPROTO_IPV6) return 0; /* e.g. IPV6_V6ONLY on what is now an IPv4 socket */
    return real_setsockopt(fd, level, name, value, len);
}
