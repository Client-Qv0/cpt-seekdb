0000000000012520 <mvdb::exact::distances4_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]>:
   12520:	55                   	push   %rbp
   12521:	49 89 f9             	mov    %rdi,%r9
   12524:	49 89 c8             	mov    %rcx,%r8
   12527:	48 89 d7             	mov    %rdx,%rdi
   1252a:	48 89 e5             	mov    %rsp,%rbp
   1252d:	41 54                	push   %r12
   1252f:	53                   	push   %rbx
   12530:	48 8b 06             	mov    (%rsi),%rax
   12533:	4c 8b 5e 08          	mov    0x8(%rsi),%r11
   12537:	4c 8b 66 10          	mov    0x10(%rsi),%r12
   1253b:	49 89 c2             	mov    %rax,%r10
   1253e:	48 8b 5e 18          	mov    0x18(%rsi),%rbx
   12542:	31 f6                	xor    %esi,%esi
   12544:	41 83 e2 03          	and    $0x3,%r10d
   12548:	75 0d                	jne    12557 <mvdb::exact::distances4_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x37>
   1254a:	48 8d 50 01          	lea    0x1(%rax),%rdx
   1254e:	4c 39 da             	cmp    %r11,%rdx
   12551:	0f 84 11 01 00 00    	je     12668 <mvdb::exact::distances4_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x148>
   12557:	49 8b 09             	mov    (%r9),%rcx
   1255a:	48 c1 e8 02          	shr    $0x2,%rax
   1255e:	48 8d 14 8d 00 00 00 	lea    0x0(,%rcx,4),%rdx
   12565:	00 
   12566:	48 0f af c2          	imul   %rdx,%rax
   1256a:	49 01 c2             	add    %rax,%r10
   1256d:	48 85 c9             	test   %rcx,%rcx
   12570:	0f 84 12 01 00 00    	je     12688 <mvdb::exact::distances4_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x168>
   12576:	49 8b 41 30          	mov    0x30(%r9),%rax
   1257a:	c5 e0 57 db          	vxorps %xmm3,%xmm3,%xmm3
   1257e:	40 84 f6             	test   %sil,%sil
   12581:	0f 85 a1 00 00 00    	jne    12628 <mvdb::exact::distances4_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x108>
   12587:	4d 89 d9             	mov    %r11,%r9
   1258a:	41 83 e3 03          	and    $0x3,%r11d
   1258e:	c5 e9 57 d2          	vxorpd %xmm2,%xmm2,%xmm2
   12592:	4c 89 e6             	mov    %r12,%rsi
   12595:	49 c1 e9 02          	shr    $0x2,%r9
   12599:	48 c1 ee 02          	shr    $0x2,%rsi
   1259d:	41 83 e4 03          	and    $0x3,%r12d
   125a1:	4c 0f af ca          	imul   %rdx,%r9
   125a5:	48 0f af f2          	imul   %rdx,%rsi
   125a9:	4d 01 d9             	add    %r11,%r9
   125ac:	49 89 db             	mov    %rbx,%r11
   125af:	83 e3 03             	and    $0x3,%ebx
   125b2:	49 c1 eb 02          	shr    $0x2,%r11
   125b6:	4c 01 e6             	add    %r12,%rsi
   125b9:	4c 0f af da          	imul   %rdx,%r11
   125bd:	31 d2                	xor    %edx,%edx
   125bf:	49 01 db             	add    %rbx,%r11
   125c2:	4a 8d 04 98          	lea    (%rax,%r11,4),%rax
   125c6:	4d 29 da             	sub    %r11,%r10
   125c9:	4d 29 d9             	sub    %r11,%r9
   125cc:	4c 29 de             	sub    %r11,%rsi
   125cf:	90                   	nop
   125d0:	c5 fa 10 04 b0       	vmovss (%rax,%rsi,4),%xmm0
   125d5:	c4 e3 79 21 20 10    	vinsertps $0x10,(%rax),%xmm0,%xmm4
   125db:	c5 e2 5a 0c 97       	vcvtss2sd (%rdi,%rdx,4),%xmm3,%xmm1
   125e0:	c4 e2 7d 19 c9       	vbroadcastsd %xmm1,%ymm1
   125e5:	c4 a1 7a 10 04 90    	vmovss (%rax,%r10,4),%xmm0
   125eb:	c4 a3 79 21 04 88 10 	vinsertps $0x10,(%rax,%r9,4),%xmm0,%xmm0
   125f2:	48 83 c2 01          	add    $0x1,%rdx
   125f6:	48 83 c0 10          	add    $0x10,%rax
   125fa:	c5 f8 16 c4          	vmovlhps %xmm4,%xmm0,%xmm0
   125fe:	c5 fc 5a c0          	vcvtps2pd %xmm0,%ymm0
   12602:	c5 fd 5c c1          	vsubpd %ymm1,%ymm0,%ymm0
   12606:	c5 fd 59 c0          	vmulpd %ymm0,%ymm0,%ymm0
   1260a:	c5 ed 58 d0          	vaddpd %ymm0,%ymm2,%ymm2
   1260e:	48 39 d1             	cmp    %rdx,%rcx
   12611:	75 bd                	jne    125d0 <mvdb::exact::distances4_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0xb0>
   12613:	c5 fd 51 d2          	vsqrtpd %ymm2,%ymm2
   12617:	c4 c1 7d 11 10       	vmovupd %ymm2,(%r8)
   1261c:	c5 f8 77             	vzeroupper
   1261f:	5b                   	pop    %rbx
   12620:	41 5c                	pop    %r12
   12622:	5d                   	pop    %rbp
   12623:	c3                   	ret
   12624:	0f 1f 40 00          	nopl   0x0(%rax)
   12628:	4a 8d 14 90          	lea    (%rax,%r10,4),%rdx
   1262c:	c5 e9 57 d2          	vxorpd %xmm2,%xmm2,%xmm2
   12630:	31 c0                	xor    %eax,%eax
   12632:	66 0f 1f 44 00 00    	nopw   0x0(%rax,%rax,1)
   12638:	c5 e2 5a 0c 87       	vcvtss2sd (%rdi,%rax,4),%xmm3,%xmm1
   1263d:	c4 e2 7d 19 c9       	vbroadcastsd %xmm1,%ymm1
   12642:	c5 fc 5a 02          	vcvtps2pd (%rdx),%ymm0
   12646:	48 83 c0 01          	add    $0x1,%rax
   1264a:	c5 fd 5c c1          	vsubpd %ymm1,%ymm0,%ymm0
   1264e:	48 83 c2 10          	add    $0x10,%rdx
   12652:	c5 fd 59 c0          	vmulpd %ymm0,%ymm0,%ymm0
   12656:	c5 ed 58 d0          	vaddpd %ymm0,%ymm2,%ymm2
   1265a:	48 39 c1             	cmp    %rax,%rcx
   1265d:	75 d9                	jne    12638 <mvdb::exact::distances4_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x118>
   1265f:	eb b2                	jmp    12613 <mvdb::exact::distances4_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0xf3>
   12661:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
   12668:	48 8d 50 02          	lea    0x2(%rax),%rdx
   1266c:	4c 39 e2             	cmp    %r12,%rdx
   1266f:	0f 85 e2 fe ff ff    	jne    12557 <mvdb::exact::distances4_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x37>
   12675:	48 8d 50 03          	lea    0x3(%rax),%rdx
   12679:	48 39 da             	cmp    %rbx,%rdx
   1267c:	40 0f 94 c6          	sete   %sil
   12680:	e9 d2 fe ff ff       	jmp    12557 <mvdb::exact::distances4_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x37>
   12685:	0f 1f 00             	nopl   (%rax)
   12688:	c5 e9 57 d2          	vxorpd %xmm2,%xmm2,%xmm2
   1268c:	eb 85                	jmp    12613 <mvdb::exact::distances4_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0xf3>
   1268e:	66 90                	xchg   %ax,%ax

