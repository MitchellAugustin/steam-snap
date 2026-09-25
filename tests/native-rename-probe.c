#include <errno.h>
#include <stdio.h>

int main(int argc, char **argv)
{
    if (argc != 3)
        return 2;
    if (rename(argv[1], argv[2]) != 0) {
        int status = errno;
        perror("rename");
        return status;
    }
    puts("rename succeeded");
    return 0;
}