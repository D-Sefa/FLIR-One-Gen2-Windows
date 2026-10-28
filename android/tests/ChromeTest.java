package com.dsefa.flir;
public class ChromeTest{public static void main(String[] args){ChromeState c=new ChromeState();c.touch(1000);if(c.hidden(4999)||!c.hidden(5000))throw new AssertionError("Hide only after four idle seconds");c.touch(6000);if(c.hidden(6001))throw new AssertionError("Interaction restores controls");System.out.println("PASS four-second idle controls / touch reset");}}
